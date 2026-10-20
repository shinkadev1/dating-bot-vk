"""Доставка событий Chat API в ВК. События лежат в Redis, бот читает их по WebSocket.

Бот запускается отдельно от Compose Chat API, поэтому к Redis он не подключается:
тот же поток отдаёт `/api/v1/events/vk`.
"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

from websockets.asyncio.client import connect

from app.api_client import ChatApiError, chat_api
from app.config import CHAT_API_URL, EVENTS_CONSUMER, chat_api_headers
from app.gateway import gateway
from app.handlers import cancel_search_timeout
from app.peer import Peer
from app.ui import FOUND_TEXT, PARTNER_LEFT_TEXT, UNDELIVERED_TEXT, format_partner

_RECONNECT_DELAY_SECONDS = 3.0
# Живые реплики идут тем же токеном сообщества. 10 сообщений/с оставляют запас под диалоги.
_NOTICE_INTERVAL = 0.1


async def _deliver(body: dict) -> None:
    """Шлёт событие адресату. Если ВК не принял, API закрывает его диалог."""
    to = body["to"]
    peer = Peer(str(to["bot_key"]), int(to["user_id"]))
    kind = body.get("type")
    if kind == "partner_found":
        cancel_search_timeout(peer)
        delivered = await gateway.send(peer, FOUND_TEXT, "chat")
    elif kind == "message":
        delivered = await gateway.send(peer, format_partner(str(body.get("text") or "")), "line")
    elif kind == "media":
        media_id = str(body.get("media_id") or "")
        if not media_id:
            print(f"Событие media без файла для {peer}", flush=True)
            return
        try:
            data, content_type, file_kind = await chat_api.fetch_media(media_id)
        except ChatApiError as exc:
            print(f"Не скачал медиа {media_id} для {peer}: {exc}", flush=True)
            return
        delivered = await gateway.send_media(peer, file_kind, content_type, data)
    elif kind == "partner_left":
        cancel_search_timeout(peer)
        if body.get("reason") == "undeliverable":
            sent = await gateway.send(peer, UNDELIVERED_TEXT, "main")
        else:
            sent = await gateway.send(peer, PARTNER_LEFT_TEXT, "partner_left")
        print(f"Уход собеседника {peer}: {'доставлено' if sent else 'не доставлено'}", flush=True)
        return
    else:
        print(f"Неизвестное событие Chat API: {kind}", flush=True)
        return
    if delivered:
        return
    try:
        await chat_api.delivery_failed(peer)
    except ChatApiError as exc:
        print(f"Не сообщил API о недоставке {peer}: {exc}", flush=True)


async def _deliver_notice(body: dict) -> None:
    """Пишет уведомление в диалог. Недоступный человек не снимается с поиска и из пары."""
    if body.get("type") != "notice":
        return
    to = body.get("to") or {}
    text = str(body.get("text") or "").strip()
    if not text or "bot_key" not in to or "user_id" not in to:
        return
    peer = Peer(str(to["bot_key"]), int(to["user_id"]))
    await asyncio.sleep(_NOTICE_INTERVAL)
    await gateway.send(peer, text, "line")


async def _handle(event: dict) -> None:
    try:
        await _deliver(event)
    except Exception as exc:  # noqa: BLE001 — битое событие не должно стопорить очередь
        print(f"Не обработал событие {event!r}: {type(exc).__name__}: {exc}", flush=True)


async def _handle_notice(event: dict) -> None:
    try:
        await _deliver_notice(event)
    except Exception as exc:  # noqa: BLE001
        print(f"Не обработал уведомление {event!r}: {type(exc).__name__}: {exc}", flush=True)


async def _listen(path: str, handler) -> None:
    """Держит WebSocket: каждое событие доставляется и подтверждается по порядку."""
    url = f"{CHAT_API_URL.replace('http', 'ws', 1)}{path}?consumer={quote(EVENTS_CONSUMER)}"
    while True:
        try:
            async with connect(
                url,
                additional_headers=chat_api_headers(),
                open_timeout=15,
                ping_interval=20,
                ping_timeout=20,
            ) as socket:
                print(f"Читаю события Chat API: {url}", flush=True)
                async for raw in socket:
                    message = json.loads(raw)
                    await handler(message["event"])
                    await socket.send(json.dumps({"ack": message["id"]}))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — обрыв или перезапуск Chat API
            print(f"WebSocket событий: {type(exc).__name__}: {exc}", flush=True)
        await asyncio.sleep(_RECONNECT_DELAY_SECONDS)


async def consume_events() -> None:
    await _listen("/api/v1/events/vk", _handle)


async def consume_broadcasts() -> None:
    await _listen("/api/v1/broadcasts/vk", _handle_notice)
