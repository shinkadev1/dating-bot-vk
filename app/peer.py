"""Адресат сообщения: сообщество ВК и пользователь."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Peer:
    """Куда слать ответ. bot_key — сообщество, в которое человек написал."""

    bot_key: str
    user_id: int
    platform: str = "vk"
