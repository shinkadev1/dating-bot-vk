"""Доставка событий Chat API в ВК из Redis Streams."""

from __future__ import annotations

import asyncio
import json

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.api_client import ChatApiError, chat_api
from app.config import EVENTS_CONSUMER, REDIS_URL
from app.gateway import gateway
from app.handlers import cancel_search_timeout
from app.peer import Peer
from app.ui import FOUND_TEXT, PARTNER_LEFT_TEXT, UNDELIVERED_TEXT, format_partner

_GROUP = "bots"
_STREAM = "chat:events:vk"
_BROADCAST_STREAM = "chat:broadcast:vk"
_PENDING = "0"
_NEW = ">"
_BLOCK_MS = 5000
# Живые реплики идут тем же токеном сообщества. 10 сообщений/с оставляют запас под диалоги.
_NOTICE_INTERVAL = 0.1


async def _ensure_group(redis: Redis, stream: str, start: str = "$") -> None:
    try:
        await redis.xgroup_create(stream, _GROUP, id=start, mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


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


async def _handle(fields: dict, deliver) -> None:
    try:
        await deliver(json.loads(fields["data"]))
    except Exception as exc:  # noqa: BLE001 — битое событие не должно стопорить очередь
        print(f"Не обработал событие {fields!r}: {type(exc).__name__}: {exc}", flush=True)


async def _consume(stream: str, deliver, *, start: str = "$") -> None:
    """Сначала дочитывает события, не подтверждённые до перезапуска, потом ждёт новые."""
    # Таймаут сокета длиннее блокирующего XREADGROUP, иначе чтение обрывается.
    redis = Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_timeout=_BLOCK_MS / 1000 + 10,
        socket_connect_timeout=5,
    )
    try:
        await _ensure_group(redis, stream, start)
        cursors = {stream: _PENDING}
        print(f"Читаю события Chat API: {stream}", flush=True)
        while True:
            try:
                batches = await redis.xreadgroup(_GROUP, EVENTS_CONSUMER, cursors, count=50, block=_BLOCK_MS)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — Redis может перезапускаться
                print(f"Не прочитал события: {type(exc).__name__}: {exc}", flush=True)
                await asyncio.sleep(1)
                continue
            for name, entries in batches or []:
                if not entries and cursors[name] == _PENDING:
                    cursors[name] = _NEW
                for entry_id, fields in entries:
                    await _handle(fields, deliver)
                    await redis.xack(name, _GROUP, entry_id)
                    if cursors[name] != _NEW:
                        cursors[name] = entry_id
    finally:
        await redis.aclose()


async def consume_events() -> None:
    await _consume(_STREAM, _deliver)


async def consume_broadcasts() -> None:
    # С нуля, чтобы уведомление, записанное до старта бота, не потерялось.
    await _consume(_BROADCAST_STREAM, _deliver_notice, start="0")
