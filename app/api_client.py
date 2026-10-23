"""Клиент Chat API: бот действует от имени своих пользователей по сервисному токену."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.mock_api import MockChatApi

import httpx

from app.config import CHAT_API_SERVICE_TOKEN, CHAT_API_URL, DEV_MODE, chat_api_headers
from app.peer import Peer


class ChatApiError(Exception):
    """API недоступен или ответил ошибкой."""


class NotChattingError(ChatApiError):
    """У пользователя уже нет активного диалога."""


class NotPremiumError(ChatApiError):
    """Медиа может отправить только пользователь с премиумом."""


@dataclass(frozen=True)
class SendResult:
    delivered: bool
    phase: str


class ChatApiClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 10.0) -> None:
        self._http = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/api/v1",
            headers=chat_api_headers(token),
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, peer: Peer, action: str, json: dict | None = None) -> Any:
        path = f"/peers/{peer.platform}/{peer.bot_key}/{peer.user_id}/{action}"
        try:
            response = await self._http.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise ChatApiError(f"{method} {path}: {type(exc).__name__}: {exc}") from exc
        if response.status_code == httpx.codes.CONFLICT:
            raise NotChattingError(response.text)
        if response.is_error:
            raise ChatApiError(f"{method} {path}: HTTP {response.status_code} {response.text}")
        if response.status_code == httpx.codes.NO_CONTENT:
            return None
        return response.json()

    async def visit(self, peer: Peer) -> None:
        await self._request("POST", peer, "visit")

    async def register_channel(self, platform: str, external_id: str, title: str) -> None:
        """Сообщает Chat API, что бот подключён к сообществу."""
        path = "/channels"
        try:
            response = await self._http.post(
                path,
                json={"platform": platform, "external_id": external_id, "title": title},
            )
        except httpx.HTTPError as exc:
            raise ChatApiError(f"POST {path}: {type(exc).__name__}: {exc}") from exc
        if response.is_error:
            raise ChatApiError(f"POST {path}: HTTP {response.status_code} {response.text}")

    async def phase(self, peer: Peer) -> str:
        return (await self._request("GET", peer, "state"))["phase"]

    async def search(self, peer: Peer) -> str:
        """Ставит в поиск. Возвращает chatting, если пара нашлась сразу."""
        return (await self._request("POST", peer, "search"))["phase"]

    async def stop(self, peer: Peer) -> bool:
        """True, если был поиск или диалог."""
        return (await self._request("POST", peer, "stop"))["was_active"]

    async def report(self, peer: Peer) -> str:
        """Закрывает диалог с пометкой жалобы и ставит в поиск. Возвращает новую фазу."""
        return (await self._request("POST", peer, "report"))["phase"]

    async def send_message(self, peer: Peer, text: str) -> SendResult:
        body = await self._request("POST", peer, "messages", {"text": text})
        return SendResult(delivered=body["delivered"], phase=body["phase"])

    async def store_media(self, peer: Peer, kind: str, data: bytes) -> str:
        """Кладёт байты в Chat API. Возвращает ключ объекта в S3."""
        path = f"/peers/{peer.platform}/{peer.bot_key}/{peer.user_id}/media"
        try:
            response = await self._http.post(
                path,
                data={"kind": kind},
                files={"file": ("upload.bin", data, "application/octet-stream")},
                timeout=180,
            )
        except httpx.HTTPError as exc:
            raise ChatApiError(f"POST {path}: {type(exc).__name__}: {exc}") from exc
        if response.status_code == httpx.codes.CONFLICT:
            raise NotChattingError(response.text)
        if response.status_code == httpx.codes.FORBIDDEN and "премиум" in response.text.casefold():
            raise NotPremiumError(response.text)
        if response.is_error:
            raise ChatApiError(f"POST {path}: HTTP {response.status_code} {response.text}")
        return str(response.json()["key"])

    async def fetch_media(self, media_id: str) -> tuple[bytes, str, str]:
        """Байты, MIME и вид файла, который Chat API поставил в очередь этому боту."""
        path = f"/media/{media_id}"
        try:
            response = await self._http.get(path, timeout=180)
        except httpx.HTTPError as exc:
            raise ChatApiError(f"GET {path}: {type(exc).__name__}: {exc}") from exc
        if response.is_error:
            raise ChatApiError(f"GET {path}: HTTP {response.status_code} {response.text}")
        content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip()
        kind = response.headers.get("x-media-kind") or "photo"
        return response.content, content_type, kind

    async def delivery_failed(self, peer: Peer) -> None:
        await self._request("POST", peer, "delivery-failed")


def build_chat_api() -> ChatApiClient | MockChatApi:
    """Настоящий клиент или локальная заглушка, если включён DEV_MODE."""
    if DEV_MODE:
        from app.mock_api import MockChatApi

        return MockChatApi()
    return ChatApiClient(CHAT_API_URL, CHAT_API_SERVICE_TOKEN)


chat_api = build_chat_api()
