"""Кнопка «📍 Выбрать город» (бывшая «🌍 Выбрать комнату») и список городов."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.handlers import choose_room
from app.ui import DATING_ROOMS_BTN, DEFAULT_ROOM, ROOM_ROWS, ROOMS, build_dating_keyboard, build_rooms_keyboard

# Названия городов и раскладка — в app/content/content.json (lists.ROOMS, keyboards.ROOMS_KEYBOARD).
CITIES = [ROOMS[k] for row in ROOM_ROWS for k in row]


class ChooseCityTest(unittest.TestCase):
    def test_dating_keyboard_has_city_button(self):
        rows = json.loads(build_dating_keyboard())["buttons"]
        actions = {json.loads(b["action"]["payload"])["command"]: b["action"] for r in rows for b in r}
        self.assertEqual(actions["dating_rooms"]["label"], DATING_ROOMS_BTN)

    def test_cities_keyboard(self):
        self.assertEqual(DEFAULT_ROOM, "spb")
        rows = json.loads(build_rooms_keyboard("msk"))["buttons"]
        self.assertEqual([len(r) for r in rows], [len(r) for r in ROOM_ROWS])
        labels = [b["action"]["label"] for r in rows for b in r]
        self.assertEqual([l.replace(" ✅", "") for l in labels], CITIES)
        self.assertIn(ROOMS["msk"] + " ✅", labels)
        self.assertTrue(all(len(l) <= 40 for l in labels))
        payloads = [json.loads(b["action"]["payload"]) for r in rows for b in r]
        self.assertTrue(all(p["command"] == "room" for p in payloads))


class StaleRoomButtonTest(unittest.IsolatedAsyncioTestCase):
    async def test_old_room_button_is_answered_and_shows_cities(self):
        event = MagicMock()
        event.user_id = 5
        event.payload = json.dumps({"command": "room", "room": "talk"})
        event.edit_message = AsyncMock()
        event.show_snackbar = AsyncMock()
        await choose_room(event, "main")
        keyboard = json.loads(event.edit_message.call_args.kwargs["keyboard"])
        labels = [b["action"]["label"] for r in keyboard["buttons"] for b in r]
        self.assertIn(ROOMS["spb"] + " ✅", labels)
        event.show_snackbar.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
