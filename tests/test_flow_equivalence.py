"""Поведение бота ВК на flow.yaml совпадает со снимком кода до перехода (tests/fixtures/ui_snapshot.json).

Снимок снят со старого кода (origin/master 47f1237), где тексты, клавиатуры и маршруты были константами
в app/ui.py и цепочкой if в app/handlers.py. Тест заново собирает то же самое на новом коде
(tests/snapshot_collect.py) и сравнивает: константы, JSON клавиатур, форматы, классификацию входов,
ответы на сообщения и нажатия, исходящие вызовы VK API (с sha256 картинок) и события Chat API.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

os.environ["DEV_MODE"] = "False"

import snapshot_collect  # noqa: E402

from app import ui  # noqa: E402

SNAPSHOT = json.loads((Path(__file__).parent / "fixtures" / "ui_snapshot.json").read_text(encoding="utf-8"))

# Намеренные отличия от старого кода. Остальное совпадает побайтно.
# Нажатия inline-кнопок dating_rooms, dating_settings и next раньше молча игнорировались (таких кнопок не было),
# теперь любое действие из реестра ACTIONS выполняется по имени из payload (см. ButtonActionTests).
CHANGED_BUTTONS = {
    f"cmd:{command}|{phase}|{mode}|{as_text}"
    for command in ("dating_rooms", "dating_settings", "next")
    for phase in ("idle", "searching", "chatting")
    for mode in ("A", "B", "C", "E")
    for as_text in (0, 1)
}

NEW: dict = {}


def setUpModule() -> None:
    # Набор текстов берётся из снимка, чтобы вход в тест был тем же, что при съёмке.
    inputs = sorted({key.split("|")[0] for key in SNAPSHOT["incoming"] if not key.startswith(("payload:", "age:", "mode:", "media:"))})
    NEW.update(snapshot_collect.collect_all(inputs=inputs))


class SnapshotTests(unittest.TestCase):
    maxDiff = None

    def assert_section(self, section: str, skip: frozenset[str] | set[str] = frozenset()) -> None:
        old, new = SNAPSHOT[section], NEW[section]
        missing = [key for key in old if key not in new]
        self.assertEqual(missing, [], f"{section}: нет ключей")
        for key, expected in old.items():
            if key in skip:
                continue
            self.assertEqual(new[key], expected, f"{section}: {key}")

    def test_texts_and_public_names(self) -> None:
        # Старые публичные имена сохранены; новые (build_keyboard …) допустимы.
        self.assertEqual(sorted(set(SNAPSHOT["texts"]["__names__"]) - set(NEW["texts"]["__names__"])), [])
        self.assert_section("texts", skip={"__names__"})

    def test_keyboards_json(self) -> None:
        self.assert_section("keyboards")

    def test_formats(self) -> None:
        self.assert_section("formats")

    def test_classification_of_inputs(self) -> None:
        """_is_start/_is_report на каждый текст и payload каждой команды."""
        self.assert_section("classification")

    def test_parsers(self) -> None:
        self.assert_section("parse")

    def test_incoming_messages(self) -> None:
        """Вход × payload × фаза × ожидание возраста × режим дают те же вызовы gateway и Chat API."""
        self.assert_section("incoming")

    def test_vk_message_handler(self) -> None:
        self.assert_section("vk_handler")

    def test_button_presses(self) -> None:
        """Нажатия inline-кнопок: ответ на нажатие, правка клавиатуры, тосты, вызовы gateway и API."""
        self.assert_section("buttons", skip=CHANGED_BUTTONS)

    def test_start_buttons_in_history(self) -> None:
        self.assert_section("history")

    def test_gateway_output(self) -> None:
        """messages.send целиком (текст, клавиатура, вложение) и загрузки картинок (sha256)."""
        self.assert_section("gateway")
        self.assert_section("senders")

    def test_events(self) -> None:
        self.assert_section("events")

    def test_snapshot_is_not_trivial(self) -> None:
        """Защита от пустого снимка: тест не должен проходить на пустых данных."""
        self.assertGreater(len(SNAPSHOT["incoming"]), 1500)
        self.assertGreater(len(SNAPSHOT["classification"]), 500)
        self.assertGreater(len(SNAPSHOT["gateway"]), 80)
        self.assertGreater(len(SNAPSHOT["buttons"]), 400)
        self.assertEqual(len(SNAPSHOT["keyboards"]), len(NEW["keyboards"]))
        self.assertIn("{\"command\": \"room\", \"room\": \"msk\"}", json.dumps(NEW["keyboards"]["rooms:"]).replace("\\", ""))


class ButtonActionTests(unittest.TestCase):
    """Отличия от старого кода: действия из реестра выполняются по имени и для inline-кнопок."""

    def test_changed_buttons_now_run_their_action(self) -> None:
        for key in sorted(CHANGED_BUTTONS):
            new = NEW["buttons"][key]
            self.assertEqual(new["empty_answers"], 1, key)
            command = key.split("|")[0].removeprefix("cmd:")
            if command == "dating_rooms":
                self.assertEqual([c[0] for c in new["gateway"]], ["send_rooms"], key)
            elif command == "dating_settings":
                self.assertEqual([c[0] for c in new["gateway"]], ["send_settings"], key)
            elif "|E|" not in key:
                self.assertTrue(new["gateway"] or new["api"], key)

    def test_next_requires_exact_caption(self) -> None:
        import asyncio
        from unittest import mock

        from app import handlers

        async def run(text: str) -> bool:
            with mock.patch.object(handlers, "_next_partner", mock.AsyncMock()):
                return await handlers.handle_next(object(), text, False)

        self.assertTrue(asyncio.run(run(ui.CHAT_BTN_NEXT)))
        self.assertFalse(asyncio.run(run(ui.CHAT_BTN_NEXT.lower())))
        self.assertFalse(asyncio.run(run(ui.CHAT_BTN_NEXT.upper())))

    def test_ui_keeps_old_public_names(self) -> None:
        for name in SNAPSHOT["texts"]["__names__"]:
            self.assertTrue(hasattr(ui, name), name)


if __name__ == "__main__":
    unittest.main()
