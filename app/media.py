"""Скачивает фото, видео, кружок или голосовое из сообщения ВК и отдаёт байты в Chat API."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from vkbottle.bot import Message

from app.api_client import NotChattingError, chat_api
from app.peer import Peer

_LIMITS = {
    "photo": 20 * 1024 * 1024,
    "voice": 20 * 1024 * 1024,
    "video_note": 32 * 1024 * 1024,
    "video": 100 * 1024 * 1024,
}
_MP4 = ("mp4_1080", "mp4_720", "mp4_480", "mp4_360", "mp4_240", "mp4_144")
_UA = {"User-Agent": "Mozilla/5.0"}


def _dump(value: object) -> dict:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if dump is None:
        return {}
    raw = dump(mode="json")
    return raw if isinstance(raw, dict) else {}


def _payloads(message: Message) -> list[dict]:
    return [item for item in (_dump(attachment) for attachment in message.attachments or []) if item]


def _classify(item: dict) -> tuple[str, dict] | None:
    """Кружок ВК приходит как video с type=video_message, голосовое — как audio_message."""
    kind = item.get("type")
    if kind == "photo" and isinstance(item.get("photo"), dict):
        return "photo", item["photo"]
    if kind == "audio_message" and isinstance(item.get("audio_message"), dict):
        return "voice", item["audio_message"]
    if kind == "video_message" and isinstance(item.get("video_message"), dict):
        return "video_note", item["video_message"]
    if kind == "video" and isinstance(item.get("video"), dict):
        video = item["video"]
        return ("video_note" if video.get("type") == "video_message" else "video"), video
    return None


def _photo_url(photo: dict) -> str | None:
    orig = photo.get("orig_photo")
    if isinstance(orig, dict) and isinstance(orig.get("url"), str) and orig["url"].startswith("http"):
        return orig["url"]
    best_url = None
    best_area = -1
    for size in photo.get("sizes") or []:
        if not isinstance(size, dict):
            continue
        url = size.get("url") or size.get("src")
        if not isinstance(url, str) or not url.startswith("http"):
            continue
        area = int(size.get("width") or 0) * int(size.get("height") or 0)
        if area >= best_area:
            best_url = url
            best_area = area
    return best_url


def _best_mp4(files: object) -> str | None:
    if not isinstance(files, dict):
        return None
    for name in _MP4:
        url = files.get(name)
        if isinstance(url, str) and url.startswith("http"):
            return url
    for name, url in files.items():
        if str(name).startswith("mp4") and isinstance(url, str) and url.startswith("http"):
            return url
    return None


async def _download(url: str, limit: int) -> bytes:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        async with client.stream("GET", url, headers=_UA) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes(64 * 1024):
                total += len(chunk)
                if total > limit:
                    raise ValueError(f"файл больше {limit} байт")
                chunks.append(chunk)
    if not chunks:
        raise ValueError("пустой ответ")
    return b"".join(chunks)


async def _vk_method(api: Any, method: str, params: dict) -> dict:
    response = await api.request(method, params)
    body = _dump(response)
    nested = body.get("response")
    if "items" not in body and isinstance(nested, dict):
        return nested
    return body


async def _video_url(api: Any, video: dict) -> str | None:
    direct = video.get("link_mp4")
    if isinstance(direct, str) and direct.startswith("http"):
        return direct
    owner_id = video.get("owner_id")
    video_id = video.get("id")
    if owner_id is None or video_id is None:
        return None
    ref = f"{owner_id}_{video_id}"
    if video.get("access_key"):
        ref = f"{ref}_{video['access_key']}"
    for attempt in range(6):
        body = await _vk_method(api, "video.get", {"videos": ref})
        if body.get("error"):
            print(f"video.get не отдал {ref}: {body['error']}", flush=True)
            return None
        items = body.get("items") or []
        first = items[0] if items and isinstance(items[0], dict) else {}
        url = _best_mp4(first.get("files"))
        if url:
            return url
        # Кружок часто приходит, пока VK ещё пишет processing=1. Пустой список — видео ещё не в каталоге.
        processing = first.get("processing")
        if processing in (1, True) or (not items and attempt < 3):
            await asyncio.sleep(1.5)
            continue
        return None
    return None


async def _bytes_for(api: Any, kind: str, payload: dict) -> bytes | None:
    limit = _LIMITS[kind]
    if kind == "photo":
        url = _photo_url(payload)
    elif kind == "voice":
        url = payload.get("link_ogg") if isinstance(payload.get("link_ogg"), str) else payload.get("link_mp3")
        if not isinstance(url, str) or not url.startswith("http"):
            url = None
    else:
        url = await _video_url(api, payload)
    if not url:
        return None
    return await _download(url, limit)


async def store_vk_media(message: Message, peer: Peer) -> str:
    """Сохраняет вложения диалога. ok — все легли в S3, failed — хотя бы одно нет, left — диалог уже закрыт."""
    payloads = _payloads(message)
    found = [item for item in (_classify(payload) for payload in payloads) if item is not None]
    if not found:
        if payloads:
            print(f"VK вложения без медиа {peer}: {[item.get('type') for item in payloads]}", flush=True)
        return "none"
    print(f"VK медиа {peer}: {[kind for kind, _payload in found]}", flush=True)
    saved = 0
    failed = False
    for kind, payload in found:
        try:
            data = await _bytes_for(message.ctx_api, kind, payload)
            if not data:
                failed = True
                print(f"Нет файла {kind} для {peer}", flush=True)
                continue
            key = await chat_api.store_media(peer, kind, data)
        except NotChattingError:
            return "left"
        except Exception as exc:  # noqa: BLE001 — одно вложение не должно ронять остальные
            failed = True
            print(f"Не сохранил {kind} {peer}: {type(exc).__name__}: {exc}", flush=True)
            continue
        saved += 1
        print(f"Медиа сохранено {peer} {kind} {key} ({len(data)} байт)", flush=True)
    if failed or saved == 0:
        return "failed"
    return "ok"
