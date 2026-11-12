"""Промо премиума: флаг promo в partner_left и в ответе /stop, экраны во flow."""

import unittest
from unittest.mock import AsyncMock, patch

from app import events, flow, handlers
from app.api_client import StopResult
from app.peer import Peer
from app.premium import PremiumOffer
from app.ui import PARTNER_LEFT_TEXT, STOPPED_TEXT, UNDELIVERED_TEXT

TO = {"bot_key": "1", "user_id": 42}
BODY = {"type": "partner_left", "to": TO, "promo": True}
PROMO_TAIL = (
    "💎 Так и не нашёл, кого искал? Попробуй с премиумом — фото, видео и голосовые в чате "
    "и никакой рекламы.\n🔥 Пошлый чат\n📍 Поиск по городу\n👫 Выбор пола партнёра\n\n"
    "Пробный период — 1 ₽."
)
LEFT_TEXT = "Собеседник закончил диалог 😔\n\n" + PROMO_TAIL
STOPPED_PROMO_TEXT = "Диалог остановлен.\n\n" + PROMO_TAIL


def _buttons(screen):
    return [b for row in screen.buttons for b in row]


class PartnerLeftPromoTest(unittest.IsolatedAsyncioTestCase):
    def _patches(self, offer):
        return (
            patch.object(events, "premium_offer", AsyncMock(return_value=offer)),
            patch.object(events.gateway, "send_screen", AsyncMock(return_value=True)),
            patch.object(events.gateway, "send", AsyncMock(return_value=True)),
            patch.object(events.chat_api, "delivery_failed", AsyncMock()),
            patch.object(events, "cancel_search_timeout"),
        )

    async def test_promo_without_premium_sends_promo_screen(self):
        p1, p2, p3, p4, p5 = self._patches(PremiumOffer("https://pay"))
        with p1, p2 as screen, p3 as send, p4 as failed, p5:
            await events._deliver(BODY)
        screen.assert_awaited_once()
        self.assertEqual(screen.await_args.args[1], "partner_left_promo")
        send.assert_not_awaited()
        failed.assert_not_awaited()

    async def test_promo_with_premium_sends_regular(self):
        p1, p2, p3, p4, p5 = self._patches(PremiumOffer("https://pay", active=True))
        with p1, p2 as screen, p3 as send, p4, p5:
            await events._deliver(BODY)
        screen.assert_not_awaited()
        self.assertEqual(send.await_args.args[1:], (PARTNER_LEFT_TEXT, "partner_left"))

    async def test_no_flag_does_not_check_premium(self):
        p1, p2, p3, p4, p5 = self._patches(PremiumOffer("https://pay"))
        with p1 as offer, p2 as screen, p3 as send, p4, p5:
            await events._deliver({"type": "partner_left", "to": TO})
        offer.assert_not_awaited()
        screen.assert_not_awaited()
        self.assertEqual(send.await_args.args[1:], (PARTNER_LEFT_TEXT, "partner_left"))

    async def test_undeliverable_with_promo(self):
        p1, p2, p3, p4, p5 = self._patches(PremiumOffer("https://pay"))
        with p1 as offer, p2 as screen, p3 as send, p4, p5:
            await events._deliver({**BODY, "reason": "undeliverable"})
        offer.assert_not_awaited()
        screen.assert_not_awaited()
        self.assertEqual(send.await_args.args[1:], (UNDELIVERED_TEXT, "main"))


class StopPromoTest(unittest.IsolatedAsyncioTestCase):
    peer = Peer("1", 42)

    async def _run(self, result, offer):
        with patch.object(handlers.chat_api, "phase", AsyncMock(return_value="chatting")), \
                patch.object(handlers.chat_api, "stop", AsyncMock(return_value=result)), \
                patch.object(handlers, "premium_offer", AsyncMock(return_value=offer)), \
                patch.object(handlers.gateway, "send_screen", AsyncMock(return_value=True)) as screen, \
                patch.object(handlers.gateway, "send", AsyncMock(return_value=True)) as send, \
                patch.object(handlers, "cancel_search_timeout"):
            await handlers.stop_active(self.peer)
        return screen, send

    async def test_promo_sends_stopped_promo(self):
        screen, send = await self._run(StopResult(True, True), PremiumOffer("https://pay"))
        self.assertEqual(screen.await_args.args[1], "stopped_promo")
        send.assert_not_awaited()

    async def test_promo_with_premium_sends_regular(self):
        screen, send = await self._run(StopResult(True, True), PremiumOffer("https://pay", active=True))
        screen.assert_not_awaited()
        self.assertEqual(send.await_args.args[1:], (STOPPED_TEXT, "main"))

    async def test_no_promo_sends_regular(self):
        screen, send = await self._run(StopResult(True, False), PremiumOffer("https://pay"))
        screen.assert_not_awaited()
        self.assertEqual(send.await_args.args[1:], (STOPPED_TEXT, "main"))


class FlowScreensTest(unittest.TestCase):
    def test_partner_left_promo(self):
        screen = flow.get().screen("partner_left_promo")
        self.assertEqual(screen.text, LEFT_TEXT)
        self.assertEqual(screen.image, "images/premium.png")
        self.assertEqual(screen.on, "partner_left")
        buttons = _buttons(screen)
        self.assertEqual(len(buttons), 3)
        self.assertEqual(buttons[0].url, "{premium_url}")

    def test_stopped_promo(self):
        screen = flow.get().screen("stopped_promo")
        self.assertEqual(screen.text, STOPPED_PROMO_TEXT)
        self.assertEqual(screen.image, "images/premium.png")
        buttons = _buttons(screen)
        self.assertEqual(len(buttons), 2)
        self.assertEqual(buttons[0].url, "{premium_url}")

    def test_old_promo_removed(self):
        self.assertNotIn("promo", events.EVENTS)
        with self.assertRaises(Exception):
            flow.get().screen("premium_promo")


if __name__ == "__main__":
    unittest.main()
