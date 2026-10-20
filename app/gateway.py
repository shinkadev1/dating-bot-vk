"""Доставка текста и медиа в то сообщество ВК, которому пишет человек."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.peer import Peer
from app.ui import (
    build_chat_keyboard,
    build_main_keyboard,
    build_partner_left_keyboard,
    empty_keyboard,
    new_random_id,
)


def vk_keyboard(kind: str) -> str | None:
    """Клавиатура под текстом. None — реплика собеседника, без кнопок диалога."""
    if kind == "line":
        return None
    if kind == "chat":
        return build_chat_keyboard()
    if kind == "partner_left":
        return build_partner_left_keyboard()
    return build_main_keyboard()


def _is_inline(keyboard: str) -> bool:
    try:
        data = json.loads(keyboard)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and bool(data.get("inline"))


def _message_id(response: object) -> int | None:
    if isinstance(response, int):
        return response
    if isinstance(response, dict):
        value = response.get("response", response.get("message_id"))
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


async def _send_plain(api: Any, peer_id: int, text: str, keyboard: str | None = None) -> object:
    payload: dict[str, Any] = {"peer_id": peer_id, "message": text, "random_id": new_random_id()}
    if keyboard is not None:
        payload["keyboard"] = keyboard
    return await api.messages.send(**payload)


async def send_vk(api: Any, peer_id: int, text: str, keyboard: str | None) -> None:
    """Пишет в диалог ВК. Inline-кнопки крепятся к тексту и снимают старую нижнюю клавиатуру."""
    if keyboard is None or not _is_inline(keyboard):
        try:
            await _send_plain(api, peer_id, text, keyboard)
        except Exception as exc:
            print(
                f"Клавиатура не принята для peer={peer_id}, шлю текст: {type(exc).__name__}: {exc}",
                flush=True,
            )
            await _send_plain(api, peer_id, text)
        return
    try:
        sent = await _send_plain(api, peer_id, text, empty_keyboard())
    except Exception as exc:
        print(
            f"Не снял нижнюю клавиатуру peer={peer_id}: {type(exc).__name__}: {exc}",
            flush=True,
        )
        await _send_plain(api, peer_id, text, keyboard)
        return
    message_id = _message_id(sent)
    if message_id is None:
        await _send_plain(api, peer_id, text, keyboard)
        return
    try:
        await api.messages.edit(
            peer_id=peer_id,
            message=text,
            message_id=message_id,
            keyboard=keyboard,
        )
    except Exception as exc:
        print(
            f"Не прикрепил кнопки peer={peer_id}, шлю отдельным сообщением: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        await _send_plain(api, peer_id, text, keyboard)


class Gateway:
    """Знает API каждого подключённого сообщества и шлёт ответ через него."""

    def __init__(self) -> None:
        self._apis: dict[str, Any] = {}

    def add(self, bot_key: str, api: Any) -> None:
        """Регистрирует API сообщества. Ключ — id сообщества."""
        self._apis[bot_key] = api

    async def send(self, peer: Peer, text: str, kind: str) -> bool:
        """Отправляет текст и клавиатуру. False, если ВК не принял сообщение."""
        try:
            api = self._apis.get(peer.bot_key)
            if api is None:
                raise RuntimeError(f"Нет сообщества ВК {peer.bot_key}")
            await send_vk(api, peer.user_id, text, vk_keyboard(kind))
            return True
        except Exception as exc:  # noqa: BLE001 — сбой доставки не должен ронять общий обработчик
            print(
                f"Не удалось написать vk:{peer.bot_key}:{peer.user_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )
            return False

    async def send_media(self, peer: Peer, kind: str, content_type: str, data: bytes) -> bool:
        """Кладёт файл в диалог ВК. False — человек недоступен, диалог надо закрыть.

        Ошибка загрузки файла диалог не обрывает: собеседник просто не увидит это вложение.
        Кружок уходит обычным видео: токен сообщества кружок создать не может.
        """
        api = self._apis.get(peer.bot_key)
        if api is None:
            print(f"Нет сообщества ВК {peer.bot_key}", flush=True)
            return False
        try:
            attachment = await _vk_attachment(api, peer.user_id, kind, content_type, data)
            await api.messages.send(
                peer_id=peer.user_id,
                random_id=new_random_id(),
                attachment=attachment,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            print(
                f"Не отправил медиа vk:{peer.bot_key}:{peer.user_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )
            return not _vk_blocked(exc)


def _vk_blocked(exc: BaseException) -> bool:
    """Человек запретил сообщения сообщества или удалён."""
    code = getattr(exc, "code", None)
    if code in {7, 900, 901, 902}:
        return True
    text = str(exc)
    return any(f"[{item}]" in text for item in (7, 900, 901, 902))


def _as_data(value: object) -> object:
    if isinstance(value, dict) and "response" in value:
        return value["response"]
    dump = getattr(value, "model_dump", None)
    if dump is None:
        return value
    raw = dump(mode="json")
    if isinstance(raw, dict) and "response" in raw:
        return raw["response"]
    return raw


def _as_dict(value: object) -> dict:
    data = _as_data(value)
    return data if isinstance(data, dict) else {}


def _filename(kind: str, content_type: str) -> str:
    ext = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
        "video/mp4": "mp4",
        "video/webm": "webm",
        "video/quicktime": "mov",
        "audio/ogg": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
    }.get(content_type, "bin")
    return f"{kind}.{ext}"


_VK_VERSION = "5.199"
_UPLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://vk.com/",
}


class VkCallError(RuntimeError):
    def __init__(self, method: str, code: int | None, message: str) -> None:
        super().__init__(f"{method} [{code}] {message}")
        self.code = code


def _form_value(value: object) -> str:
    """ВК ждёт photo и file строкой. Список из ответа загрузки иначе теряется."""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


async def _vk_method(api: Any, method: str, params: dict) -> object:
    token = getattr(api, "token", None)
    if not token:
        return _as_data(await api.request(method, params))
    form = {key: _form_value(value) for key, value in params.items()}
    form["access_token"] = token
    form["v"] = _VK_VERSION
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"https://api.vk.com/method/{method}", data=form)
        response.raise_for_status()
    body = response.json()
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        code = error.get("error_code")
        raise VkCallError(method, code if isinstance(code, int) else None, str(error.get("error_msg") or ""))
    if isinstance(body, dict) and "response" in body:
        return body["response"]
    return body


async def _upload_file(url: str, field: str, filename: str, data: bytes, content_type: str) -> dict:
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            url,
            files={field: (filename, data, content_type)},
            headers=_UPLOAD_HEADERS,
        )
        response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("ВК вернул не объект при загрузке файла")
    if body.get("error"):
        raise RuntimeError(f"ВК не принял файл: {body['error']}")
    return body


async def _vk_attachment(api: Any, peer_id: int, kind: str, content_type: str, data: bytes) -> str:
    name = _filename(kind, content_type)
    if kind == "photo":
        server = _as_dict(await _vk_method(api, "photos.getMessagesUploadServer", {"peer_id": peer_id}))
        uploaded = await _upload_file(str(server["upload_url"]), "photo", name, data, content_type)
        photo_value = _form_value(uploaded.get("photo"))
        if photo_value in {"", "[]", "undefined"}:
            raise RuntimeError("ВК не принял фото при загрузке")
        saved = await _vk_method(
            api,
            "photos.saveMessagesPhoto",
            {"photo": photo_value, "server": uploaded["server"], "hash": uploaded["hash"]},
        )
        photo = _as_dict(saved[0] if isinstance(saved, list) and saved else saved)
        attachment = f"photo{photo['owner_id']}_{photo['id']}"
        access_key = photo.get("access_key")
        return f"{attachment}_{access_key}" if access_key else attachment
    if kind == "voice":
        server = _as_dict(
            await _vk_method(
                api,
                "docs.getMessagesUploadServer",
                {"peer_id": peer_id, "type": "audio_message"},
            )
        )
        uploaded = await _upload_file(str(server["upload_url"]), "file", name, data, content_type)
        saved = _as_dict(await _vk_method(api, "docs.save", {"file": uploaded["file"]}))
        audio = saved.get("audio_message") if isinstance(saved.get("audio_message"), dict) else None
        if audio and audio.get("id") is not None:
            return f"audio_message{audio['owner_id']}_{audio['id']}"
        doc = saved.get("doc") if isinstance(saved.get("doc"), dict) else saved
        return f"doc{doc['owner_id']}_{doc['id']}"
    server = _as_dict(
        await _vk_method(
            api,
            "video.save",
            {"name": name, "is_private": 1, "wallpost": 0, "repeat": 0},
        )
    )
    await _upload_file(str(server["upload_url"]), "video_file", name, data, content_type)
    attachment = f"video{server['owner_id']}_{server['video_id']}"
    access_key = server.get("access_key")
    return f"{attachment}_{access_key}" if access_key else attachment


gateway = Gateway()
