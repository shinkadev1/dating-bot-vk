"""Правки из CRM доходят до пользователя: новый экран и кнопка goto работают без изменений кода."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["DEV_MODE"] = "False"

import yaml  # noqa: E402

from app import flow, gateway as gateway_module, handlers  # noqa: E402
from app.gateway import Gateway  # noqa: E402
from app.peer import Peer  # noqa: E402
from app.premium import PremiumOffer  # noqa: E402

BOT = "123"
PEER = Peer(BOT, 42)
PAY_URL = "https://pay.example.test/?x=1"


def build_flow(tmp: Path) -> flow.Flow:
    """Боевой flow.yaml плюс новые экраны и кнопки, как после правки в CRM."""
    data = yaml.load((flow.FLOW_DIR / "flow.yaml").read_text(encoding="utf-8"), Loader=flow._Loader)
    shutil.copytree(flow.FLOW_DIR / "images", tmp / "images")
    screens = data["screens"]
    screens["main"]["buttons"] += [
        [{"text": "🎁 Акция", "goto": "promo", "style": "primary"}],
        [{"text": "Цикл", "goto": "loop_a", "style": "secondary"}],
        [{"text": "К тарифам", "goto": "premium", "style": "primary"}],
        [{"text": "К диалогу", "goto": "chat", "style": "primary"}],
    ]
    screens["promo"] = {
        "title": "Акция",
        "text": "Скидка недели",
        "image": "images/greeting.jpg",
        "keyboard": "inline",
        "buttons": [
            [
                {"text": "Сайт", "url": "https://example.com/", "style": "primary"},
                {"text": "Назад", "goto": "main", "style": "secondary"},
            ]
        ],
        "next": "thanks",
        "pos": {"x": 0, "y": 1080},
    }
    screens["thanks"] = {
        "title": "Спасибо",
        "text": "Спасибо, что заглянули",
        "keyboard": "reply",
        "buttons": [[{"text": "Вернуться", "goto": "promo", "style": "success"}]],
        "pos": {"x": 320, "y": 1080},
    }
    screens["loop_a"] = {"title": "A", "text": "экран A", "next": "loop_b", "pos": {"x": 0, "y": 1260}}
    screens["loop_b"] = {"title": "B", "text": "экран B", "next": "loop_a", "pos": {"x": 320, "y": 1260}}
    path = tmp / "flow.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return flow.load(path)


def labels(keyboard: str) -> list[list[str]]:
    return [[b["action"]["label"] for b in row] for row in json.loads(keyboard)["buttons"]]


class GotoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        self.flow = build_flow(tmp)
        patcher = patch.object(flow, "get", return_value=self.flow)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.api = MagicMock()
        self.api.messages.send = AsyncMock(return_value=1)
        self.uploads: list[tuple[str, str, int]] = []

        async def attachment(_api, peer_id, kind, content_type, data):
            self.uploads.append((kind, content_type, len(data)))
            return "photo-1_2"

        self.real_gateway = Gateway()
        self.real_gateway.add(BOT, self.api)
        self.chat = MagicMock()
        self.chat.visit = AsyncMock()
        self.chat.phase = AsyncMock(return_value="idle")
        self.chat.search = AsyncMock(return_value="searching")
        self.chat.stop = AsyncMock(return_value=True)
        offer = AsyncMock(return_value=PremiumOffer(PAY_URL))
        patches = (
            (handlers, "gateway", self.real_gateway),
            (handlers, "chat_api", self.chat),
            (handlers, "premium_offer", offer),
            (gateway_module, "premium_offer", offer),
            (gateway_module, "_vk_attachment", attachment),
        )
        for module, name, value in patches:
            p = patch.object(module, name, value)
            p.start()
            self.addCleanup(p.stop)
        handlers._awaiting_age.clear()
        self.addCleanup(handlers._awaiting_age.clear)
        self.addCleanup(self._cancel_timeouts)

    def _cancel_timeouts(self) -> None:
        for task in handlers._search_timeouts.values():
            task.cancel()
        handlers._search_timeouts.clear()

    def sent(self) -> list[dict]:
        return [dict(c.kwargs) for c in self.api.messages.send.call_args_list]

    def event(self, payload: dict | str, user_id: int | None = 42) -> MagicMock:
        event = MagicMock()
        event.payload = payload
        event.user_id = user_id
        event.peer_id = user_id
        event.send_empty_answer = AsyncMock()
        return event

    async def test_reply_button_goto_sends_screen_then_next(self) -> None:
        payload = {"command": "go", "screen": "promo"}
        await handlers.handle_incoming(PEER, "🎁 Акция", payload)
        first, second = self.sent()
        self.assertEqual((first["message"], first["attachment"]), ("Скидка недели", "photo-1_2"))
        self.assertEqual(self.uploads, [("photo", "image/jpeg", len((flow.FLOW_DIR / "images" / "greeting.jpg").read_bytes()))])
        keyboard = json.loads(first["keyboard"])
        self.assertTrue(keyboard["inline"])
        site, back = keyboard["buttons"][0]
        self.assertEqual((site["action"]["type"], site["action"]["link"]), ("open_link", "https://example.com/"))
        self.assertEqual(json.loads(back["action"]["payload"]), {"command": "go", "screen": "main"})
        # next: thanks — следующий экран уходит сразу, с нижней клавиатурой из flow.
        self.assertEqual(second["message"], "Спасибо, что заглянули")
        self.assertFalse(json.loads(second["keyboard"])["inline"])
        self.assertEqual(labels(second["keyboard"]), [["Вернуться"]])
        self.chat.phase.assert_not_called()

    async def test_typed_token_is_case_and_space_insensitive(self) -> None:
        await handlers.handle_incoming(PEER, "  🎁 АКЦИЯ ", {})
        self.assertEqual(self.sent()[0]["message"], "Скидка недели")

    async def test_goto_from_the_new_screen_button(self) -> None:
        await handlers.handle_incoming(PEER, "Вернуться", {"command": "go", "screen": "promo"})
        self.assertEqual(self.sent()[0]["message"], "Скидка недели")

    async def test_unknown_goto_payload_is_ignored_like_any_text(self) -> None:
        self.chat.phase.return_value = "chatting"
        self.chat.send_message = AsyncMock(return_value=SimpleNamespace(delivered=True))
        await handlers.handle_incoming(PEER, "привет", {"command": "go", "screen": "nowhere"})
        self.chat.send_message.assert_awaited_once()
        self.assertEqual(self.sent(), [])
        await handlers.handle_incoming(PEER, "привет", {"command": "go", "screen": ["x"]})

    async def test_next_loop_is_cut(self) -> None:
        await handlers.handle_incoming(PEER, "Цикл", {"command": "go", "screen": "loop_a"})
        self.assertEqual([m["message"] for m in self.sent()], ["экран A", "экран B"])

    async def test_goto_handler_screen_uses_its_code(self) -> None:
        await handlers.handle_incoming(PEER, "К тарифам", {"command": "go", "screen": "premium"})
        (message,) = self.sent()
        self.assertEqual(message["message"], self.flow.screen("premium").text)
        links = [row[0]["action"]["link"] for row in json.loads(message["keyboard"])["buttons"]]
        self.assertEqual(links[0], PAY_URL + "&plan=trial")
        self.assertEqual(len(links), 4)

    async def test_goto_chat_screen_uses_chat_keyboard(self) -> None:
        await handlers.handle_incoming(PEER, "К диалогу", {"command": "go", "screen": "chat"})
        (message,) = self.sent()
        self.assertEqual(message["message"], self.flow.screen("chat").text)
        self.assertEqual(labels(message["keyboard"]), [["🔍 Новый собеседник"], ["💎 Купить премиум"], ["Остановить диалог"]])

    async def test_goto_interrupts_age_prompt(self) -> None:
        for text, payload in (("🎁 Акция", {}), ("", {"command": "go", "screen": "promo"})):
            handlers._awaiting_age.add(PEER)
            self.api.messages.send.reset_mock()
            await handlers.handle_incoming(PEER, text, payload)
            self.assertNotIn(PEER, handlers._awaiting_age)
            self.assertEqual(self.sent()[0]["message"], "Скидка недели")

    async def test_inline_goto_callback(self) -> None:
        event = self.event({"command": "go", "screen": "promo"})
        await handlers.vk_start_handler(BOT)(event)
        event.send_empty_answer.assert_awaited_once()
        self.assertEqual([m["message"] for m in self.sent()], ["Скидка недели", "Спасибо, что заглянули"])

    async def test_unknown_goto_callback_only_answers(self) -> None:
        event = self.event(json.dumps({"command": "go", "screen": "nowhere"}))
        await handlers.vk_start_handler(BOT)(event)
        event.send_empty_answer.assert_awaited_once()
        self.assertEqual(self.sent(), [])

    async def test_inline_action_runs_by_name_not_through_text(self) -> None:
        """Нажатие не превращается в текст: ожидание возраста его не перехватывает."""
        handlers._awaiting_age.add(PEER)
        event = self.event({"command": "premium"})
        await handlers.vk_start_handler(BOT)(event)
        event.send_empty_answer.assert_awaited_once()
        self.assertEqual(self.sent()[0]["message"], self.flow.screen("premium").text)
        self.assertNotIn(self.flow.screen("age").text, [m["message"] for m in self.sent()])

    async def test_inline_action_next_uses_phase(self) -> None:
        await handlers.vk_start_handler(BOT)(self.event({"command": "next"}))
        self.chat.search.assert_awaited_once()
        self.chat.search.reset_mock()
        self.chat.phase.return_value = "searching"
        await handlers.vk_start_handler(BOT)(self.event({"command": "next"}))
        self.chat.search.assert_not_called()
        self.assertEqual(self.sent()[-1]["message"], self.flow.text("searching"))

    async def test_gateway_screen_without_text_and_image_is_skipped(self) -> None:
        self.assertFalse(await self.real_gateway.send_screen(PEER, "notice"))
        self.assertEqual(self.sent(), [])

    async def test_gateway_send_screen_unknown_api_returns_false(self) -> None:
        self.assertFalse(await self.real_gateway.send_screen(Peer("other", 1), "loop_a"))


if __name__ == "__main__":
    unittest.main()
