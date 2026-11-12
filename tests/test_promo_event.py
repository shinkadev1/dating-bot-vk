"""Событие promo: экран premium_promo без побочных эффектов для диалога."""

import unittest
from unittest.mock import AsyncMock, patch

from app import events
from app import flow
from app.premium import PremiumOffer

BODY = {"type": "promo", "to": {"bot_key": "1", "user_id": 42}}
TEXT = (
    "💎 Так и не нашёл, кого искал? Попробуй с премиумом — фото, видео и голосовые в чате "
    "и никакой рекламы. Пробный период — 1 ₽."
)


class PromoEventTest(unittest.IsolatedAsyncioTestCase):
    def _patches(self, offer, sent=True):
        return (
            patch.object(events, "premium_offer", AsyncMock(return_value=offer)),
            patch.object(events.gateway, "send_screen", AsyncMock(return_value=sent)),
            patch.object(events.chat_api, "delivery_failed", AsyncMock()),
            patch.object(events, "cancel_search_timeout"),
        )

    async def test_promo_sends_screen(self):
        p1, p2, p3, p4 = self._patches(PremiumOffer("https://pay"))
        with p1, p2 as send, p3 as failed, p4 as cancel:
            await events._deliver(BODY)
        send.assert_awaited_once()
        self.assertEqual(send.await_args.args[1], "premium_promo")
        failed.assert_not_awaited()
        cancel.assert_not_called()

    async def test_failed_send_does_not_close_dialog(self):
        p1, p2, p3, p4 = self._patches(PremiumOffer("https://pay"), sent=False)
        with p1, p2, p3 as failed, p4:
            await events._deliver(BODY)
        failed.assert_not_awaited()

    async def test_active_premium_skips(self):
        p1, p2, p3, p4 = self._patches(PremiumOffer("https://pay", active=True))
        with p1, p2 as send, p3 as failed, p4:
            await events._deliver(BODY)
        send.assert_not_awaited()
        failed.assert_not_awaited()

    def test_screen_in_flow(self):
        screen = flow.get().screen("premium_promo")
        self.assertEqual(screen.text, TEXT)
        self.assertEqual(screen.image, "images/premium.png")
        self.assertEqual(screen.on, "promo")
        self.assertEqual(len([b for row in screen.buttons for b in row]), 2)
        self.assertIn("promo", events.EVENTS)


if __name__ == "__main__":
    unittest.main()
