"""Режим последнего поиска пользователя: adult — «Пошлый чат», нет записи — обычный поиск.

Отдельный модуль, чтобы режим видели и обработчики, и шлюз (клавиатура зависит от режима).
"""

from __future__ import annotations

from app.peer import Peer

ADULT_MODE = "adult"
search_modes: dict[Peer, str] = {}


def is_adult(peer: Peer) -> bool:
    return search_modes.get(peer) == ADULT_MODE
