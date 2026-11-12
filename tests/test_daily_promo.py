"""Ежедневная рассылка: notice с полем screen показывает экран flow, кнопка start запускает поиск."""

import unittest
from unittest.mock import AsyncMock, patch

from app import events, flow, handlers, ui

TO = {"bot_key": "1", "user_id": 42}


def _buttons(screen):
    return [b for row in screen.buttons for b in row]


class DailyNoticeTest(unittest.IsolatedAsyncioTestCase):
    def _patches(self):
        return (
            patch.object(events.gateway, "send_screen", AsyncMock(return_value=True)),
            patch.object(events.gateway, "send_notice", AsyncMock(return_value=True)),
            patch.object(events.chat_api, "delivery_failed", AsyncMock()),
            patch.object(events, "_NOTICE_INTERVAL", 0),
        )

    async def test_screen_notice_sends_screen(self):
        p1, p2, p3, p4 = self._patches()
        with p1 as screen, p2 as notice, p3 as failed, p4:
            await events._deliver_notice({"type": "notice", "to": TO, "screen": "daily_promo"})
        screen.assert_awaited_once()
        self.assertEqual(screen.await_args.args[1], "daily_promo")
        self.assertEqual(screen.await_args.args[0].user_id, 42)
        notice.assert_not_awaited()
        failed.assert_not_awaited()

    async def test_text_notice_as_before(self):
        p1, p2, p3, p4 = self._patches()
        with p1 as screen, p2 as notice, p3, p4:
            await events._deliver_notice({"type": "notice", "to": TO, "text": "привет"})
        screen.assert_not_awaited()
        notice.assert_awaited_once()

    async def test_unknown_screen_with_text_falls_back(self):
        p1, p2, p3, p4 = self._patches()
        with p1 as screen, p2 as notice, p3, p4:
            await events._deliver_notice({"type": "notice", "to": TO, "screen": "nope", "text": "привет"})
        screen.assert_not_awaited()
        notice.assert_awaited_once()

    async def test_unknown_screen_without_text_skipped(self):
        p1, p2, p3, p4 = self._patches()
        with p1 as screen, p2 as notice, p3 as failed, p4:
            await events._deliver_notice({"type": "notice", "to": TO, "screen": "nope"})
        screen.assert_not_awaited()
        notice.assert_not_awaited()
        failed.assert_not_awaited()


class DailyScreenTest(unittest.TestCase):
    def test_screen_shape(self):
        screen = flow.get().screen("daily_promo")
        self.assertEqual(screen.keyboard, "inline")
        self.assertIsNone(screen.image)
        self.assertIsNone(screen.on)
        buttons = _buttons(screen)
        self.assertEqual(buttons[0].action, "start")
        self.assertIsNotNone(buttons[1].url)
        self.assertTrue(ui.uses_premium_link("daily_promo"))

    def test_start_button_runs_search(self):
        runner = handlers._button_runner("start", {})
        self.assertIs(runner, handlers.connect_with_partner)


if __name__ == "__main__":
    unittest.main()
