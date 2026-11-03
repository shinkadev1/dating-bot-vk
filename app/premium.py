"""Личная ссылка на оплату премиума и срок премиума пользователя.

Ссылка из Chat API действует 24 часа и содержит подписанный токен пользователя.
Её можно отдавать только кнопкой OpenLink: в тексте сообщения ВК раскроет сниппет
и его краулер откроет страницу оплаты раньше человека.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.api_client import chat_api
from app.peer import Peer
from app.ui import PREMIUM_URL

# Клавиатура живого диалога уходит часто: ссылку берём из кэша. Час намного меньше суток жизни ссылки.
LINK_TTL = 60 * 60
# После ошибки Chat API не дёргаем его на каждом сообщении, но и статичную ссылку долго не держим.
FALLBACK_TTL = 5 * 60
_CACHE_LIMIT = 10_000
_MSK = timezone(timedelta(hours=3))


@dataclass(frozen=True)
class PremiumOffer:
    url: str
    active: bool = False
    until: datetime | None = None

    @property
    def until_text(self) -> str:
        """Дата окончания премиума по Москве: ДД.ММ.ГГГГ."""
        if self.until is None:
            return ""
        until = self.until if self.until.tzinfo else self.until.replace(tzinfo=timezone.utc)
        return until.astimezone(_MSK).strftime("%d.%m.%Y")


FALLBACK_OFFER = PremiumOffer(PREMIUM_URL)

_cache: dict[tuple[str, int], tuple[float, PremiumOffer]] = {}


def _parse_until(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


async def premium_offer(peer: Peer, *, fresh: bool = False) -> PremiumOffer:
    """Ссылка на оплату и статус премиума. fresh — не брать из кэша (промо, отказ в медиа).

    Кэш общий для всех сообществ: покупка привязана к аккаунту платформы, а не к боту.
    При ошибке или 503 возвращает статичную PREMIUM_URL.
    """
    key = (peer.platform, peer.user_id)
    now = time.monotonic()
    cached = _cache.get(key)
    if not fresh and cached is not None and cached[0] > now:
        return cached[1]
    try:
        body = await chat_api.premium_link(peer)
        url = str(body.get("url") or "") if isinstance(body, dict) else ""
        if not url.startswith("https://"):
            raise ValueError("в ответе нет https-ссылки")
        offer = PremiumOffer(
            url=url,
            active=bool(body.get("premium_active")),
            until=_parse_until(body.get("premium_until")),
        )
        ttl = LINK_TTL
    except Exception as exc:  # noqa: BLE001 — без личной ссылки остаётся статичная
        print(
            f"WARNING: нет личной ссылки на премиум {peer}, отдаю статичную: {type(exc).__name__}: {exc}",
            flush=True,
        )
        offer = FALLBACK_OFFER
        ttl = FALLBACK_TTL
    if len(_cache) >= _CACHE_LIMIT:
        for stale in [item for item, (expires, _offer) in _cache.items() if expires <= now]:
            del _cache[stale]
    _cache[key] = (now + ttl, offer)
    return offer
