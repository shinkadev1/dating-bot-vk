"""Скачивает фото, видео, кружок или голосовое из сообщения ВК и отдаёт байты в Chat API."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
from vkbottle.bot import Message

from app.api_client import NotChattingError, NotPremiumError, chat_api
from app.peer import Peer

_LIMITS = {
    "photo": 20 * 1024 * 1024,
    "voice": 20 * 1024 * 1024,
    "video_note": 32 * 1024 * 1024,
    "video": 100 * 1024 * 1024,
}
_MP4 = ("mp4_1080", "mp4_720", "mp4_480", "mp4_360", "mp4_240", "mp4_144")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://vk.com/",
    "Accept": "*/*",
}
_MP4_URL = re.compile(r"https://[^\s\"'<>\\]+")
_VIDEO_BOXES = ("video", "clip", "short_video", "video_message")


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


def _looks_like_circle(video: dict) -> bool:
    """Кружок и фигурное видеосообщение: квадрат и короткая длительность, либо заголовок ВК."""
    title = str(video.get("title") or "").lower()
    if "видеосообщен" in title:
        return True
    width = video.get("width")
    height = video.get("height")
    duration = video.get("duration")
    return (
        isinstance(width, int)
        and isinstance(height, int)
        and width > 0
        and width == height
        and isinstance(duration, int)
        and duration <= 60
    )


def _as_video(kind_hint: str, video: dict) -> tuple[str, dict] | None:
    if video.get("owner_id") is None or video.get("id") is None:
        return None
    note = kind_hint == "video_message" or video.get("type") in ("video_message", "video_note")
    if not note and video.get("type") == "NOT_SUPPORTED":
        note = _looks_like_circle(video)
    if not note and kind_hint == "video":
        note = _looks_like_circle(video)
    return ("video_note" if note else "video"), video


def _classify(item: dict) -> tuple[str, dict] | None:
    """Кружок ВК приходит как video с type=video_message, голосовое — как audio_message.

    Незнакомый библиотеке тип она помечает NOT_SUPPORTED и выбрасывает поля.
    Тогда вложение читается из сырого ответа messages.getByConversationMessageId.
    """
    kind = item.get("type")
    if kind == "photo" and isinstance(item.get("photo"), dict):
        return "photo", item["photo"]
    if kind == "audio_message" and isinstance(item.get("audio_message"), dict):
        return "voice", item["audio_message"]
    if kind == "video_message" and isinstance(item.get("video_message"), dict):
        return "video_note", item["video_message"]
    for key in _VIDEO_BOXES:
        video = item.get(key)
        if isinstance(video, dict):
            found = _as_video(key, video)
            if found is not None:
                return found
    if kind == "NOT_SUPPORTED":
        for value in item.values():
            if not isinstance(value, dict):
                continue
            if isinstance(value.get("link_ogg"), str) or isinstance(value.get("link_mp3"), str):
                return "voice", value
            if value.get("sizes") or value.get("orig_photo"):
                return "photo", value
            found = _as_video("video", value)
            if found is not None:
                return found
    return None


def _photo_urls(photo: dict) -> list[str]:
    """Сначала уменьшенные размеры: оригинал на vkuserphoto.ru чаще отвечает 429."""
    ranked: list[tuple[int, str]] = []
    for size in photo.get("sizes") or []:
        if not isinstance(size, dict):
            continue
        url = size.get("url") or size.get("src")
        if not isinstance(url, str) or not url.startswith("http"):
            continue
        area = int(size.get("width") or 0) * int(size.get("height") or 0)
        ranked.append((area, url))
    ranked.sort(key=lambda item: item[0], reverse=True)
    urls: list[str] = []
    for _, url in ranked:
        if url not in urls:
            urls.append(url)
    # Три размера, не вся лестница: каждый адрес при 429 ждёт повтор.
    picked = urls[:3]
    orig = photo.get("orig_photo")
    if isinstance(orig, dict) and isinstance(orig.get("url"), str) and orig["url"].startswith("http"):
        if orig["url"] not in picked:
            picked.append(orig["url"])
    return picked


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


def _direct_mp4(video: dict) -> str | None:
    link = video.get("link_mp4")
    if isinstance(link, str) and link.startswith("http"):
        return link
    return _best_mp4(video.get("files"))


def _same_video(item: dict, video: dict) -> dict | None:
    found = _classify(item)
    if found is None or found[0] not in ("video", "video_note"):
        return None
    other = found[1]
    if other.get("owner_id") == video.get("owner_id") and other.get("id") == video.get("id"):
        return other
    return None


def _mp4_from_html(text: str) -> str | None:
    plain = text.replace("\\/", "/").replace("\\u0026", "&")
    found = [url.rstrip("\\") for url in _MP4_URL.findall(plain) if ".mp4" in url.split("?", 1)[0]]
    if not found:
        return None

    def rank(url: str) -> int:
        for quality in (1080, 720, 480, 360, 240, 144):
            if str(quality) in url:
                return quality
        return 0

    return max(found, key=rank)


async def _download(url: str, limit: int) -> bytes:
    delay = 0.5
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=60, follow_redirects=True, headers=_HEADERS) as client:
        for attempt in range(4):
            async with client.stream("GET", url) as response:
                if response.status_code == 429 and attempt < 3:
                    await response.aread()
                    last_error = httpx.HTTPStatusError(
                        "429 Too Many Requests",
                        request=response.request,
                        response=response,
                    )
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
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
    if last_error is not None:
        raise last_error
    raise ValueError("пустой ответ")


async def _download_first(urls: list[str], limit: int) -> bytes | None:
    if not urls:
        return None
    last_error: Exception | None = None
    for url in urls:
        try:
            return await _download(url, limit)
        except Exception as exc:  # noqa: BLE001 — следующий размер может открыться
            last_error = exc
            print(f"Не скачал файл: {type(exc).__name__}: {exc}", flush=True)
    if last_error is not None:
        raise last_error
    return None


async def _vk_method(api: Any, method: str, params: dict) -> dict:
    response = await api.request(method, params)
    body = _dump(response)
    nested = body.get("response")
    if "items" not in body and isinstance(nested, dict):
        return nested
    return body


async def _raw_attachments(api: Any, peer_id: int, conversation_message_id: int) -> list[dict]:
    """Полное сообщение. Long Poll отдаёт урезанное вложение, а video.get токен сообщества не принимает."""
    try:
        body = await _vk_method(
            api,
            "messages.getByConversationMessageId",
            {
                "peer_id": peer_id,
                "conversation_message_ids": str(conversation_message_id),
                "extended": 1,
            },
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Не прочитал сообщение {conversation_message_id}: {type(exc).__name__}: {exc}", flush=True)
        return []
    items = body.get("items") or []
    message = items[0] if items and isinstance(items[0], dict) else {}
    attachments = message.get("attachments") or []
    return [item for item in attachments if isinstance(item, dict)]


def _needs_raw(payloads: list[dict]) -> bool:
    """Сырое сообщение нужно, только если библиотека не разобрала вложение. Видео и кружки не скачиваются."""
    return any(item.get("type") in (None, "NOT_SUPPORTED") for item in payloads)


async def _player_mp4(video: dict) -> str | None:
    owner_id = video.get("owner_id")
    video_id = video.get("id")
    access_key = video.get("access_key")
    if owner_id is None or video_id is None or not access_key:
        return None
    url = f"https://vk.com/video_ext.php?oid={owner_id}&id={video_id}&hash={access_key}"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=_HEADERS) as client:
            response = await client.get(url)
            response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"Плеер видео {owner_id}_{video_id} не открылся: {type(exc).__name__}: {exc}", flush=True)
        return None
    return _mp4_from_html(response.text)


async def _video_url(api: Any, video: dict, peer_id: int | None, conversation_message_id: int | None) -> str | None:
    direct = _direct_mp4(video)
    if direct:
        return direct
    current = video
    if peer_id is not None and conversation_message_id is not None:
        for attempt in range(6):
            fresh = None
            for item in await _raw_attachments(api, peer_id, conversation_message_id):
                fresh = _same_video(item, video)
                if fresh is not None:
                    break
            if fresh is not None:
                current = fresh
                direct = _direct_mp4(fresh)
                if direct:
                    return direct
            processing = current.get("processing")
            if processing in (1, True) or attempt < 2:
                await asyncio.sleep(1.5)
                continue
            break
    return await _player_mp4(current)


async def _bytes_for(
    api: Any,
    kind: str,
    payload: dict,
    *,
    peer_id: int | None,
    conversation_message_id: int | None,
) -> bytes | None:
    limit = _LIMITS[kind]
    if kind == "photo":
        return await _download_first(_photo_urls(payload), limit)
    if kind == "voice":
        url = payload.get("link_ogg") if isinstance(payload.get("link_ogg"), str) else payload.get("link_mp3")
        if not isinstance(url, str) or not url.startswith("http"):
            return None
        return await _download(url, limit)
    url = await _video_url(api, payload, peer_id, conversation_message_id)
    if not url:
        return None
    return await _download(url, limit)


async def store_vk_media(message: Message, peer: Peer) -> str:
    """Сохраняет фото и голосовые. Видео и кружки ВК не скачиваются и пользователю об этом не пишется."""
    payloads = _payloads(message)
    peer_id = message.peer_id
    conversation_message_id = message.conversation_message_id
    if _needs_raw(payloads) and peer_id is not None and conversation_message_id is not None:
        raw = await _raw_attachments(message.ctx_api, peer_id, conversation_message_id)
        if raw:
            payloads = raw
    found = [item for item in (_classify(payload) for payload in payloads) if item is not None]
    skipped = [kind for kind, _payload in found if kind in ("video", "video_note")]
    found = [item for item in found if item[0] not in ("video", "video_note")]
    if skipped:
        print(f"VK видео и кружки не скачиваются {peer}: {skipped}", flush=True)
    if not found:
        if payloads and not skipped:
            print(f"VK вложения без медиа {peer}: {[item.get('type') for item in payloads]}", flush=True)
        return "none"
    print(f"VK медиа {peer}: {[kind for kind, _payload in found]}", flush=True)
    saved = 0
    failed = False
    for kind, payload in found:
        try:
            data = await _bytes_for(
                message.ctx_api,
                kind,
                payload,
                peer_id=peer_id,
                conversation_message_id=conversation_message_id,
            )
            if not data:
                failed = True
                print(f"Нет файла {kind} для {peer}", flush=True)
                continue
            key = await chat_api.store_media(peer, kind, data)
        except NotChattingError:
            return "left"
        except NotPremiumError:
            print(f"Медиа только у премиума {peer}", flush=True)
            return "none"
        except Exception as exc:  # noqa: BLE001 — одно вложение не должно ронять остальные
            failed = True
            print(f"Не сохранил {kind} {peer}: {type(exc).__name__}: {exc}", flush=True)
            continue
        saved += 1
        print(f"Медиа сохранено {peer} {kind} {key} ({len(data)} байт)", flush=True)
    if failed or saved == 0:
        return "failed"
    return "ok"
