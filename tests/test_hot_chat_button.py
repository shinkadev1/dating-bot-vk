"""Кнопка «🔥 Пошлый чат» (бывшая «❤️ Найти девушку»): новая подпись, прежняя команда."""

import json
import unittest

from app.ui import build_dating_keyboard


class HotChatButtonTest(unittest.TestCase):
    def test_dating_keyboard_has_hot_chat_button(self):
        rows = json.loads(build_dating_keyboard())["buttons"]
        first = rows[0][0]["action"]
        self.assertEqual(first["label"], "🔥 Пошлый чат")
        self.assertEqual(json.loads(first["payload"]), {"command": "dating_find"})
        self.assertNotIn("Найти девушку", build_dating_keyboard())


if __name__ == "__main__":
    unittest.main()
