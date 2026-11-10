"""Кнопка «📍 Выбрать город» (бывшая «🌍 Выбрать комнату») и список городов."""

import json
import unittest

from app.ui import DEFAULT_ROOM, build_dating_keyboard, build_rooms_keyboard

CITIES = ["Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань", "Нижний Новгород", "Любой город"]


class ChooseCityTest(unittest.TestCase):
    def test_dating_keyboard_has_city_button(self):
        action = json.loads(build_dating_keyboard())["buttons"][0][1]["action"]
        self.assertEqual(action["label"], "📍 Выбрать город")
        self.assertEqual(json.loads(action["payload"]), {"command": "dating_rooms"})

    def test_cities_keyboard(self):
        self.assertEqual(DEFAULT_ROOM, "spb")
        rows = json.loads(build_rooms_keyboard("msk"))["buttons"]
        self.assertEqual([len(r) for r in rows], [2, 2, 2, 1])
        labels = [b["action"]["label"] for r in rows for b in r]
        self.assertEqual([l.replace(" ✅", "") for l in labels], CITIES)
        self.assertEqual(labels[0], "Москва ✅")
        self.assertTrue(all(len(l) <= 40 for l in labels))
        payloads = [json.loads(b["action"]["payload"]) for r in rows for b in r]
        self.assertTrue(all(p["command"] == "room" for p in payloads))


if __name__ == "__main__":
    unittest.main()
