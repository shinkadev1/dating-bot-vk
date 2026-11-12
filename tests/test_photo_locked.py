"""Закрытое фото: событие media с locked уходит размытой копией с кнопкой премиума."""

import unittest
from unittest.mock import AsyncMock, patch

from app import events, flow, gateway as gw
from app.peer import Peer
from app.premium import PremiumOffer
from app.ui import PHOTO_LOCKED_TEXT

TO = {"bot_key": "1", "user_id": 42}
LOCKED_TEXT = "🔒 Просмотр фото доступен только с премиумом"


class LockedEventTest(unittest.IsolatedAsyncioTestCase):
    def _patches(self):
        return (
            patch.object(events.chat_api, "fetch_media", AsyncMock(return_value=(b"jpg", "image/jpeg", "photo"))),
            patch.object(events.gateway, "send_locked_photo", AsyncMock(return_value=True)),
            patch.object(events.gateway, "send_media", AsyncMock(return_value=True)),
            patch.object(events.chat_api, "delivery_failed", AsyncMock()),
        )

    async def test_locked_sends_locked_photo(self):
        p1, p2, p3, p4 = self._patches()
        with p1 as fetch, p2 as locked, p3 as media, p4 as failed:
            await events._deliver({"type": "media", "to": TO, "media_id": "m1", "locked": True})
        fetch.assert_awaited_once_with("m1")
        self.assertEqual(locked.await_args.args, (Peer("1", 42), "image/jpeg", b"jpg"))
        media.assert_not_awaited()
        failed.assert_not_awaited()

    async def test_regular_media_unchanged(self):
        p1, p2, p3, p4 = self._patches()
        with p1, p2 as locked, p3 as media, p4:
            await events._deliver({"type": "media", "to": TO, "media_id": "m1"})
        locked.assert_not_awaited()
        self.assertEqual(media.await_args.args, (Peer("1", 42), "photo", "image/jpeg", b"jpg"))

    async def test_undelivered_locked_reports_failure(self):
        p1, p2, p3, p4 = self._patches()
        with p1, p2 as locked, p3, p4 as failed:
            locked.return_value = False
            await events._deliver({"type": "media", "to": TO, "media_id": "m1", "locked": True})
        failed.assert_awaited_once()


class LockedScreenTest(unittest.TestCase):
    def test_screen(self):
        screen = flow.get().screen("photo_locked")
        self.assertEqual(PHOTO_LOCKED_TEXT, LOCKED_TEXT)
        self.assertIsNone(screen.on)
        self.assertEqual(screen.kind, "inline")
        buttons = [b for row in screen.buttons for b in row]
        self.assertEqual([(b.text, b.url, b.style) for b in buttons], [("💎 Купить премиум", "{premium_url}", "success")])
        self.assertFalse(screen.image)


class SendLockedPhotoTest(unittest.IsolatedAsyncioTestCase):
    def _gateway(self):
        g = gw.Gateway()
        g.add("1", object())
        return g

    async def test_sends_attachment_text_and_keyboard(self):
        peer = Peer("1", 42)
        with patch.object(gw, "_vk_attachment", AsyncMock(return_value="photo1_2")) as att, \
                patch.object(gw, "premium_offer", AsyncMock(return_value=PremiumOffer("https://pay/x"))), \
                patch.object(gw, "send_vk", AsyncMock()) as send:
            ok = await self._gateway().send_locked_photo(peer, "image/jpeg", b"jpg")
        self.assertTrue(ok)
        self.assertEqual(att.await_args.args[1:], (42, "photo", "image/jpeg", b"jpg"))
        args = send.await_args.args
        self.assertEqual(args[1:3], (42, LOCKED_TEXT))
        self.assertIn("https://pay/x", args[3])
        self.assertEqual(args[4], "photo1_2")

    async def test_upload_error_keeps_dialog(self):
        with patch.object(gw, "_vk_attachment", AsyncMock(side_effect=RuntimeError("boom"))):
            ok = await self._gateway().send_locked_photo(Peer("1", 42), "image/jpeg", b"jpg")
        self.assertTrue(ok)

    async def test_unknown_community(self):
        ok = await gw.Gateway().send_locked_photo(Peer("9", 42), "image/jpeg", b"jpg")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
