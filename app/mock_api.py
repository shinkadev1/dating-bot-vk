"""Заглушка Chat API для локальной настройки бота и клавиатуры.

Фаза диалога живёт в памяти процесса. События собеседника не приходят:
поиск сразу считает, что комната найдена.
"""

from __future__ import annotations

from app.api_client import SendResult
from app.peer import Peer


class MockChatApi:
    def __init__(self) -> None:
        self._phase: dict[Peer, str] = {}

    async def aclose(self) -> None:
        return None

    def _phase_of(self, peer: Peer) -> str:
        return self._phase.get(peer, "idle")

    async def visit(self, peer: Peer) -> None:
        return None

    async def register_channel(self, platform: str, external_id: str, title: str) -> None:
        return None

    async def phase(self, peer: Peer) -> str:
        return self._phase_of(peer)

    async def search(self, peer: Peer) -> str:
        """Сразу «комната найдена»: клавиатура диалога появляется без очереди."""
        self._phase[peer] = "chatting"
        return "chatting"

    async def stop(self, peer: Peer) -> bool:
        was_active = self._phase_of(peer) != "idle"
        self._phase[peer] = "idle"
        return was_active

    async def report(self, peer: Peer) -> str:
        """Жалоба в диалоге оставляет комнату, чтобы снова показать её клавиатуру."""
        self._phase[peer] = "chatting"
        return "chatting"

    async def send_message(self, peer: Peer, text: str) -> SendResult:
        return SendResult(delivered=True, phase=self._phase_of(peer))

    async def store_media(self, peer: Peer, kind: str, data: bytes) -> str:
        return f"dev/{kind}"

    async def fetch_media(self, media_id: str) -> tuple[bytes, str, str]:
        return b"", "application/octet-stream", "photo"

    async def delivery_failed(self, peer: Peer) -> None:
        return None
