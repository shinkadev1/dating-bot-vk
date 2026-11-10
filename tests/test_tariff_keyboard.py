import json
import unittest

from app.premium import FALLBACK_OFFER, PremiumOffer
from app.ui import PREMIUM_URL, build_premium_keyboard, plan_url

PERSONAL = "https://pay.chatwithyou.site/checkout/tok?utm_source=vk&utm_campaign=premium"


def buttons(raw):
    rows = json.loads(raw)["buttons"]
    assert len(rows) <= 6
    return [(r[0]["action"]["label"], r[0]["action"]["link"], len(r)) for r in rows]


class TariffKeyboardTest(unittest.TestCase):
    def test_four_buttons_without_premium(self):
        res = buttons(build_premium_keyboard(PremiumOffer(PERSONAL)))
        self.assertEqual(
            [b[0] for b in res],
            ["🎁 Пробный 3 дня — 1 ₽", "Неделя — 299 ₽", "Месяц — 999 ₽", "Год — 2999 ₽"],
        )
        self.assertEqual(
            [b[1] for b in res], [f"{PERSONAL}&plan={p}" for p in ("trial", "week", "month", "year")]
        )
        self.assertTrue(all(b[2] == 1 for b in res))

    def test_three_buttons_with_active_premium(self):
        res = buttons(build_premium_keyboard(PremiumOffer(PERSONAL, active=True)))
        self.assertEqual([b[0] for b in res], ["Неделя — 299 ₽", "Месяц — 999 ₽", "Год — 2999 ₽"])
        self.assertNotIn("plan=trial", " ".join(b[1] for b in res))

    def test_fallback_url_without_query(self):
        res = buttons(build_premium_keyboard(FALLBACK_OFFER))
        self.assertEqual(res[0][1], PREMIUM_URL + "?plan=trial")
        self.assertEqual(plan_url("https://x.y/p?a=1&plan=old", "year"), "https://x.y/p?a=1&plan=year")


if __name__ == "__main__":
    unittest.main()
