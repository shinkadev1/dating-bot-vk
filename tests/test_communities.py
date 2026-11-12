"""CommunityManager: набор сообществ из CRM и env, перезапуск, остановка и статусы (без сети и ВК)."""

import asyncio
import io
import unittest
from contextlib import redirect_stdout

from app.api_client import ChatApiError
from app.communities import CommunityManager
from app.gateway import gateway

TOKEN_A = "vk1.a.AAAAAAAAAAAAAAAAAAAAAAAA"
TOKEN_B = "vk1.a.BBBBBBBBBBBBBBBBBBBBBBBB"
TOKEN_B2 = "vk1.a.CCCCCCCCCCCCCCCCCCCCCCCC"
TOKEN_ENV = "vk1.a.EEEEEEEEEEEEEEEEEEEEEEEE"
IDS = {TOKEN_A: 1, TOKEN_B: 2, TOKEN_B2: 2, TOKEN_ENV: 9}


class FakeHttp:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakePolling:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class FakeApi:
    def __init__(self) -> None:
        self.http_client = FakeHttp()


class FakeBot:
    def __init__(self, token: str) -> None:
        self.token = token
        self.api = FakeApi()
        self.polling = FakePolling()


class FakeChatApi:
    def __init__(self) -> None:
        self.remote: dict | Exception = {"communities": [], "disabled": []}
        self.imported: list[tuple[int, str]] = []
        self.registered: list[str] = []
        self.statuses: list[list[dict]] = []

    async def vk_communities(self) -> dict:
        if isinstance(self.remote, Exception):
            raise self.remote
        return self.remote

    async def import_vk_community(self, group_id: int, title: str, token: str) -> bool:
        self.imported.append((group_id, title))
        return True

    async def register_channel(self, platform: str, external_id: str, title: str) -> None:
        self.registered.append(external_id)

    async def report_vk_status(self, items: list[dict]) -> None:
        self.statuses.append(items)


def community(group_id: int, token: str) -> dict:
    return {"group_id": group_id, "title": f"G{group_id}", "token": token}


class CommunityManagerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.api = FakeChatApi()
        self.bots: list[FakeBot] = []
        self.preflight_calls: list[str] = []
        self.bad_tokens: set[str] = set()
        self.listening: list[str] = []

    async def asyncTearDown(self) -> None:
        for key in ("1", "2", "9"):
            gateway.remove(key)

    def preflight(self, token: str) -> tuple[int, str]:
        self.preflight_calls.append(token)
        if token in self.bad_tokens:
            raise SystemExit(f"Токен невалиден {token}")
        return IDS[token], f"G{IDS[token]}"

    def make_bot(self, token: str) -> FakeBot:
        bot = FakeBot(token)
        self.bots.append(bot)
        return bot

    async def listener(self, bot: FakeBot, group_id: str) -> None:
        self.listening.append(group_id)
        await asyncio.Event().wait()

    def manager(self, env: list[str]) -> CommunityManager:
        return CommunityManager(
            env,
            api=self.api,
            interval=0.01,
            preflight=self.preflight,
            make_bot=self.make_bot,
            attach=lambda bot, key: None,
            listener=self.listener,
        )

    async def sync(self, manager: CommunityManager) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            await manager.sync()
        await asyncio.sleep(0)
        return buffer.getvalue()

    async def test_env_only_when_api_unavailable(self) -> None:
        self.api.remote = ChatApiError("GET /channels/vk/tokens: HTTP 404")
        manager = self.manager([TOKEN_A])
        await self.sync(manager)
        self.assertEqual(manager.running_ids, ["1"])
        self.assertEqual(self.api.imported, [(1, "G1")])
        await manager.stop_all()

    async def test_union_of_api_and_unknown_env(self) -> None:
        self.api.remote = {"communities": [community(2, TOKEN_B)], "disabled": []}
        manager = self.manager([TOKEN_A])
        await self.sync(manager)
        self.assertEqual(manager.running_ids, ["1", "2"])
        self.assertIn("1", self.api.registered)
        await manager.stop_all()

    async def test_env_token_of_disabled_community_not_started(self) -> None:
        self.api.remote = {"communities": [], "disabled": [1]}
        manager = self.manager([TOKEN_A])
        await self.sync(manager)
        self.assertEqual(manager.running_ids, [])

    async def test_api_token_wins_over_env_for_same_group(self) -> None:
        self.api.remote = {"communities": [community(2, TOKEN_B2)], "disabled": []}
        manager = self.manager([TOKEN_B])
        await self.sync(manager)
        self.assertEqual(manager.running_ids, ["2"])
        self.assertEqual(self.bots[-1].token, TOKEN_B2)
        await manager.stop_all()

    async def test_disable_stops_and_cleans_up(self) -> None:
        self.api.remote = {"communities": [community(2, TOKEN_B)], "disabled": []}
        manager = self.manager([])
        await self.sync(manager)
        bot = self.bots[0]
        self.assertIn("2", gateway._apis)
        self.api.remote = {"communities": [], "disabled": [2]}
        await self.sync(manager)
        self.assertEqual(manager.running_ids, [])
        self.assertTrue(bot.polling.stopped)
        self.assertTrue(bot.api.http_client.closed)
        self.assertNotIn("2", gateway._apis)

    async def test_token_change_restarts(self) -> None:
        self.api.remote = {"communities": [community(2, TOKEN_B)], "disabled": []}
        manager = self.manager([])
        await self.sync(manager)
        first = self.bots[0]
        self.api.remote = {"communities": [community(2, TOKEN_B2)], "disabled": []}
        await self.sync(manager)
        self.assertTrue(first.api.http_client.closed)
        self.assertEqual(self.bots[-1].token, TOKEN_B2)
        self.assertEqual(manager.running_ids, ["2"])
        await manager.stop_all()

    async def test_api_failure_after_success_keeps_set(self) -> None:
        self.api.remote = {"communities": [community(2, TOKEN_B)], "disabled": []}
        manager = self.manager([])
        await self.sync(manager)
        self.api.remote = ChatApiError("GET /channels/vk/tokens: HTTP 503")
        await self.sync(manager)
        self.assertEqual(manager.running_ids, ["2"])
        self.assertEqual(len(self.bots), 1)
        await manager.stop_all()

    async def test_failed_preflight_does_not_break_others_and_is_retried(self) -> None:
        self.api.remote = {"communities": [community(1, TOKEN_A), community(2, TOKEN_B)], "disabled": []}
        self.bad_tokens.add(TOKEN_A)
        manager = self.manager([])
        output = await self.sync(manager)
        self.assertEqual(manager.running_ids, ["2"])
        self.assertNotIn(TOKEN_A, output)
        report = {item["group_id"]: item for item in self.api.statuses[-1]}
        self.assertEqual(report[2]["status"], "ok")
        self.assertEqual(report[1]["status"], "error")
        self.assertNotIn(TOKEN_A, report[1]["error"])
        self.bad_tokens.clear()
        await self.sync(manager)
        self.assertEqual(manager.running_ids, ["1", "2"])
        report = {item["group_id"]: item for item in self.api.statuses[-1]}
        self.assertEqual(report[1]["status"], "ok")
        await manager.stop_all()

    async def test_bad_env_token_is_retried_and_does_not_stop_manager(self) -> None:
        self.bad_tokens.add(TOKEN_A)
        manager = self.manager([TOKEN_A])
        await self.sync(manager)
        self.assertEqual(manager.running_ids, [])
        self.bad_tokens.clear()
        await self.sync(manager)
        self.assertEqual(manager.running_ids, ["1"])
        await manager.stop_all()

    async def test_dead_task_restarted(self) -> None:
        self.api.remote = {"communities": [community(2, TOKEN_B)], "disabled": []}
        manager = self.manager([])
        await self.sync(manager)
        manager._running["2"].task.cancel()
        await asyncio.sleep(0)
        await self.sync(manager)
        self.assertEqual(len(self.bots), 2)
        self.assertEqual(manager.running_ids, ["2"])
        await manager.stop_all()

    async def test_run_stops_everything_on_cancel(self) -> None:
        self.api.remote = {"communities": [community(2, TOKEN_B)], "disabled": []}
        manager = self.manager([])
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            runner = asyncio.create_task(manager.run())
            await asyncio.wait_for(manager.ready.wait(), 2)
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)
        self.assertEqual(manager.running_ids, [])
        self.assertTrue(self.bots[0].api.http_client.closed)

    async def test_preflight_runs_in_thread(self) -> None:
        import threading

        main_thread = threading.get_ident()
        seen: list[int] = []

        def preflight(token: str) -> tuple[int, str]:
            seen.append(threading.get_ident())
            return 1, "G1"

        manager = CommunityManager(
            [TOKEN_A],
            api=self.api,
            interval=0.01,
            preflight=preflight,
            make_bot=self.make_bot,
            attach=lambda bot, key: None,
            listener=self.listener,
        )
        await self.sync(manager)
        self.assertTrue(seen and seen[0] != main_thread)
        await manager.stop_all()


if __name__ == "__main__":
    unittest.main()
