"""Доставка текста в то сообщество ВК, которому пишет человек."""

from __future__ import annotations

import json
from typing import Any

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


gateway = Gateway()
