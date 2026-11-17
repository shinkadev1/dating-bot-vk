"""Пошлый чат: режим adult в search, премиум-гейт на 403, режим для «Следующего собеседника»."""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["DEV"] = "false"

import httpx  # noqa: E402

from app import handlers as h  # noqa: E402
from app.api_client import ChatApiClient, ChatApiError, NotPremiumError  # noqa: E402
from app.peer import Peer  # noqa: E402

PEER = Peer("main", 7)


def _client(handler) -> ChatApiClient:
    client = ChatApiClient("http://chat", "token")
    client._http = httpx.AsyncClient(base_url="http://chat/api/v1", transport=httpx.MockTransport(handler))
    return client


class SearchBodyTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_search_sends_no_body(self) -> None:
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"phase": "searching"})

        self.assertEqual(await _client(handler).search(PEER), "searching")
        self.assertTrue(seen[0].url.path.endswith("/search"))
        self.assertEqual(seen[0].content, b"")

    async def test_adult_search_sends_mode(self) -> None:
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"phase": "chatting"})

        self.assertEqual(await _client(handler).search(PEER, "adult"), "chatting")
        self.assertEqual(json.loads(seen[0].content), {"mode": "adult"})

    async def test_adult_search_403_is_not_premium(self) -> None:
        client = _client(lambda request: httpx.Response(403, json={"detail": "Пошлый чат доступен только с премиумом"}))
        with self.assertRaises(NotPremiumError):
            await client.search(PEER, "adult")

    async def test_403_without_premium_word_is_plain_error(self) -> None:
        client = _client(lambda request: httpx.Response(403, json={"detail": "Forbidden"}))
        with self.assertRaises(ChatApiError) as ctx:
            await client.search(PEER, "adult")
        self.assertNotIsInstance(ctx.exception, NotPremiumError)

    async def test_other_errors_stay_chat_api_errors(self) -> None:
        client = _client(lambda request: httpx.Response(500, text="boom"))
        with self.assertRaises(ChatApiError) as ctx:
            await client.search(PEER, "adult")
        self.assertNotIsInstance(ctx.exception, NotPremiumError)


class DatingFindTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        h._search_modes.clear()
        self.api = MagicMock()
        self.api.search = AsyncMock(return_value="searching")
        self.api.phase = AsyncMock(return_value="idle")
        self.api.visit = AsyncMock()
        self.gw = MagicMock()
        self.gw.send = AsyncMock()
        self.gw.send_premium = AsyncMock()
        offer = MagicMock(active=False)
        patches = [
            patch.object(h, "chat_api", self.api),
            patch.object(h, "gateway", self.gw),
            patch.object(h, "premium_offer", AsyncMock(return_value=offer)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    async def asyncTearDown(self) -> None:
        for task in list(h._search_timeouts.values()):
            task.cancel()
        await asyncio.gather(*h._search_timeouts.values(), return_exceptions=True)
        h._search_timeouts.clear()
        h._search_modes.clear()

    async def test_premium_user_starts_adult_search(self) -> None:
        await h.handle_dating_find(PEER)
        self.api.search.assert_awaited_once_with(PEER, "adult")
        self.gw.send_premium.assert_not_awaited()
        texts = [call.args[1] for call in self.gw.send.await_args_list]
        self.assertEqual(texts, [h.ADULT_NOTICE_TEXT, h.SEARCHING_TEXT])
        self.assertEqual(h._search_modes[PEER], "adult")

    async def test_adult_match_found_at_once(self) -> None:
        self.api.search.return_value = "chatting"
        await h.handle_dating_find(PEER)
        texts = [call.args[1] for call in self.gw.send.await_args_list]
        self.assertEqual(texts, [h.ADULT_NOTICE_TEXT, h.SEARCHING_TEXT, h.FOUND_TEXT])

    async def test_no_premium_shows_premium_screen(self) -> None:
        self.api.search.side_effect = NotPremiumError("Нужен премиум")
        await h.handle_dating_find(PEER)
        self.gw.send_premium.assert_awaited_once()
        self.assertEqual([c.args[1] for c in self.gw.send.await_args_list], [h.DATING_TEXT])
        self.assertNotIn(PEER, h._search_modes)
        self.assertEqual(h._search_timeouts, {})

    async def test_other_errors_propagate_like_normal_find(self) -> None:
        self.api.search.side_effect = ChatApiError("down")
        with self.assertRaises(ChatApiError):
            await h.handle_dating_find(PEER)

    async def test_next_keeps_adult_mode_and_normal_find_resets(self) -> None:
        await h.handle_dating_find(PEER)
        self.api.search.reset_mock()
        await h.connect_with_partner(PEER, h._search_modes.get(PEER))
        self.api.search.assert_awaited_once_with(PEER, "adult")
        self.api.search.reset_mock()
        await h.connect_with_partner(PEER)
        self.api.search.assert_awaited_once_with(PEER)
        self.assertNotIn(PEER, h._search_modes)

    async def test_next_after_adult_dialog_searches_adult(self) -> None:
        await h.handle_dating_find(PEER)
        self.api.search.reset_mock()
        await h.handle_next(PEER, h.CHAT_BTN_NEXT, False)
        self.api.search.assert_awaited_once_with(PEER, "adult")

    async def test_next_after_premium_expired_shows_premium_screen(self) -> None:
        await h.handle_dating_find(PEER)
        self.api.search.side_effect = NotPremiumError("Нужен премиум")
        await h.handle_next(PEER, h.CHAT_BTN_NEXT, False)
        self.gw.send_premium.assert_awaited_once()
        self.assertNotIn(PEER, h._search_modes)

    async def test_notice_only_on_adult_entry_not_on_next(self) -> None:
        await h.handle_dating_find(PEER)
        self.gw.send.reset_mock()
        await h.handle_incoming(PEER, "", {"command": "start"})
        self.api.search.assert_awaited_with(PEER, "adult")
        self.assertEqual([c.args[1] for c in self.gw.send.await_args_list], [h.SEARCHING_TEXT])

    async def test_normal_chat_ends_dialog_and_searches_normal(self) -> None:
        await h.handle_dating_find(PEER)
        self.api.phase.return_value = "chatting"
        self.api.stop = AsyncMock()
        self.api.search.reset_mock()
        self.gw.send.reset_mock()
        await h.handle_incoming(PEER, "", {"command": "normal_chat"})
        self.api.stop.assert_awaited_once_with(PEER)
        self.api.search.assert_awaited_once_with(PEER)
        self.assertNotIn(PEER, h._search_modes)
        texts = [c.args[1] for c in self.gw.send.await_args_list]
        self.assertEqual(texts, [h.NORMAL_NOTICE_TEXT, h.SEARCHING_TEXT])

    async def test_normal_chat_while_searching_switches_search(self) -> None:
        await h.handle_dating_find(PEER)
        self.api.phase.return_value = "searching"
        self.api.stop = AsyncMock()
        self.api.search.reset_mock()
        await h.handle_normal_chat(PEER)
        self.api.stop.assert_awaited_once_with(PEER)
        self.api.search.assert_awaited_once_with(PEER)
        self.assertNotIn(PEER, h._search_modes)

    async def test_normal_chat_outside_adult_is_safe(self) -> None:
        self.api.stop = AsyncMock()
        self.api.phase.return_value = "chatting"
        await h.handle_normal_chat(PEER)
        self.api.stop.assert_not_awaited()
        self.api.search.assert_not_awaited()
        self.api.phase.return_value = "idle"
        await h.handle_normal_chat(PEER)
        self.api.search.assert_awaited_once_with(PEER)


class AdultKeyboardTests(unittest.TestCase):
    def _labels(self, raw: str) -> list[list[str]]:
        return [[b["action"]["label"] for b in row] for row in json.loads(raw)["buttons"]]

    def test_chat_keyboard_has_normal_chat_only_in_adult(self) -> None:
        from app import ui
        from app.premium import PremiumOffer

        offer = PremiumOffer(url="https://pay.example/x", active=False, until=None)
        self.assertEqual(
            self._labels(ui.build_chat_keyboard(offer, True)),
            [["🔍 Новый собеседник"], ["💭 Обычный чат"], ["💎 Купить премиум"], ["Остановить диалог"]],
        )
        self.assertNotIn("💭 Обычный чат", sum(self._labels(ui.build_chat_keyboard(offer)), []))

    def test_bottom_keyboard_second_row_in_adult(self) -> None:
        from app import ui

        self.assertEqual(self._labels(ui.build_bottom_keyboard(True))[1], ["💭 Обычный чат"])
        self.assertNotIn("💭 Обычный чат", sum(self._labels(ui.build_bottom_keyboard()), []))


class GatewayKeyboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_picks_keyboard_by_mode(self) -> None:
        from app import gateway as g

        h._search_modes.clear()
        with patch.object(g, "premium_offer", AsyncMock(return_value=MagicMock(active=False, url="https://pay.example/x"))):
            normal = await g.vk_keyboard("chat", PEER)
            line_normal = await g.vk_keyboard("line", PEER)
            h._search_modes[PEER] = "adult"
            self.addCleanup(h._search_modes.clear)
            adult = await g.vk_keyboard("chat", PEER)
            line_adult = await g.vk_keyboard("line", PEER)
        def has(raw: str) -> bool:
            return any(b["action"]["label"] == "💭 Обычный чат" for row in json.loads(raw)["buttons"] for b in row)

        self.assertFalse(has(normal) or has(line_normal))
        self.assertTrue(has(adult) and has(line_adult))


if __name__ == "__main__":
    unittest.main()
