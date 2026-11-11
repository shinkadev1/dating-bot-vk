"""Кнопка «Пошлый чат» (бывшая «❤️ Найти девушку»): подпись из content.json, прежняя команда."""

import json
import unittest

from app.ui import DATING_FIND_BTN, build_dating_keyboard


class HotChatButtonTest(unittest.TestCase):
    def test_dating_keyboard_has_hot_chat_button(self):
        rows = json.loads(build_dating_keyboard())["buttons"]
        actions = {json.loads(b["action"]["payload"])["command"]: b["action"] for r in rows for b in r}
        self.assertEqual(actions["dating_find"]["label"], DATING_FIND_BTN)
        self.assertNotIn("❤️ Найти девушку", build_dating_keyboard())


if __name__ == "__main__":
    unittest.main()
