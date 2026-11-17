"""CommunityManager: набор сообществ из CRM и env, перезапуск, остановка и статусы (без сети и ВК)."""

import asyncio
import io
import unittest
from contextlib import redirect_stdout

from vkbottle import VKAPIError

from app.api_client import ChatApiError
from app.communities import CommunityManager, human_error
from app.gateway import gateway
from app.startup import PreflightError

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
        self.in_gateway_at_stop: bool | None = None

    def stop(self) -> None:
        self.stopped = True
        self.in_gateway_at_stop = "2" in gateway._apis


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

    async def test_gateway_removed_before_polling_stop(self) -> None:
        self.api.remote = {"communities": [community(2, TOKEN_B)], "disabled": []}
        manager = self.manager([])
        await self.sync(manager)
        bot = self.bots[0]
        await manager._stop("2")
        self.assertIs(bot.polling.in_gateway_at_stop, False)

    async def test_import_retried_until_accepted(self) -> None:
        calls: list[int] = []
        original = self.api.import_vk_community

        async def flaky(group_id: int, title: str, token: str) -> bool:
            calls.append(group_id)
            if len(calls) == 1:
                raise ChatApiError("POST /channels/vk/import: HTTP 503")
            return await original(group_id, title, token)

        self.api.import_vk_community = flaky
        manager = self.manager([TOKEN_A])
        await self.sync(manager)
        self.assertEqual(calls, [1])
        await self.sync(manager)
        self.assertEqual(calls, [1, 1])
        await self.sync(manager)
        self.assertEqual(calls, [1, 1])
        await manager.stop_all()

    async def test_first_sync_failure_does_not_stop_run(self) -> None:
        async def broken(items: list[dict]) -> None:
            raise RuntimeError("boom")

        self.api.report_vk_status = broken
        self.api.remote = {"communities": [community(2, TOKEN_B)], "disabled": []}
        manager = self.manager([])
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            runner = asyncio.create_task(manager.run())
            await asyncio.wait_for(manager.ready.wait(), 2)
            await asyncio.sleep(0.05)
            self.assertFalse(runner.done())
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)
        self.assertIn("boom", buffer.getvalue())

    async def test_human_status_texts(self) -> None:
        key = PreflightError("long instruction", kind="key", code=5, vk_message="ключ отозван")
        self.assertEqual(human_error(key, TOKEN_A), "Ключ не подошёл: ключ отозван (код 5)")
        lp = PreflightError("x", kind="longpoll", code=15, vk_message="Access denied")
        self.assertEqual(human_error(lp), "Нет доступа к Long Poll: Access denied (код 15)")
        vk = VKAPIError[5](error_msg="User authorization failed")
        self.assertEqual(human_error(vk, stopped=True), "Long Poll остановился: User authorization failed (код 5)")
        long = PreflightError("x", kind="key", code=5, vk_message="слово " * 400)
        text = human_error(long)
        self.assertLessEqual(len(text), 500)
        self.assertTrue(text.endswith("… (код 5)"))
        self.assertNotIn(TOKEN_A, human_error(RuntimeError(f"url?access_token={TOKEN_A}"), TOKEN_A))

    async def test_crm_status_is_human_readable(self) -> None:
        self.api.remote = {"communities": [community(1, TOKEN_A), community(2, TOKEN_B)], "disabled": []}

        def preflight(token: str) -> tuple[int, str]:
            if token == TOKEN_A:
                raise PreflightError("инструкция VK Error [5]", kind="key", code=5, vk_message="ключ отозван")
            return 2, "G2"

        manager = CommunityManager(
            [], api=self.api, interval=0.01, preflight=preflight, make_bot=self.make_bot,
            attach=lambda bot, key: None, listener=self.listener,
        )
        await self.sync(manager)
        report = {item["group_id"]: item for item in self.api.statuses[-1]}
        self.assertEqual(report[1]["error"], "Ключ не подошёл: ключ отозван (код 5)")
        await manager.stop_all()

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
