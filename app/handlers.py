"""Сценарии входящих сообщений: меню, поиск и диалог."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from vkbottle.bot import Message, MessageEvent

from app.api_client import ChatApiError, NotChattingError, chat_api
from app.gateway import gateway, send_vk_greeting
from app.media import store_vk_media
from app.peer import Peer
from app.ui import (
    AGE_TEXT,
    CHAT_BTN_NEXT,
    CHAT_BTN_STOP,
    DATING_TEXT,
    DEFAULT_ROOM,
    FIND_BTN,
    FOUND_TEXT,
    GENDERS,
    MEDIA_PREMIUM_TEXT,
    MENU_TEXT,
    NEW_PARTNER_BTN,
    NO_PARTNERS_TEXT,
    PARTNER_LEFT_TEXT,
    REPORT_BTN,
    REPORT_SENT_TEXT,
    ROOMS,
    ROOMS_TEXT,
    SEARCHING_TEXT,
    SERVICE_DOWN_TEXT,
    SETTINGS_TEXT,
    STOP_BTN,
    STOPPED_TEXT,
    build_main_keyboard,
    build_rooms_keyboard,
    build_settings_keyboard,
)

SEARCH_TIMEOUT_SECONDS = 30
_search_timeouts: dict[Peer, asyncio.Task[None]] = {}
_room_choice: dict[Peer, str] = {}
_gender_choice: dict[Peer, str] = {}
_age_choice: dict[Peer, str] = {}
_awaiting_age: set[Peer] = set()
_AGE_RE = re.compile(
    r"^\s*(\d{1,2})\s*(?:\+|-\s*(\d{1,2}))?\s*(?:лет|года|год|л\.?)?\s*$",
    re.IGNORECASE,
)


def peer_room(peer: Peer) -> str:
    """Комната, которую человек выбрал. По умолчанию — встречи в Петербурге."""
    return _room_choice.get(peer, DEFAULT_ROOM)


def parse_age(text: str) -> str | None:
    """Возраст из «26», «26+» или «24-34». None — не похоже на возраст."""
    match = _AGE_RE.match(text)
    if not match:
        return None
    low = int(match.group(1))
    high = int(match.group(2)) if match.group(2) else None
    if not 14 <= low <= 99:
        return None
    if high is not None and not low <= high <= 99:
        return None
    return f"{low}+" if high is None else f"{low}-{high}"


def parse_payload(raw: Any) -> dict:
    """Payload кнопки как словарь. VK отдаёт и словарь, и строку JSON; битый payload — пустой словарь."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _is_start(text: str, payload: dict) -> bool:
    """Сообщение «Начать», «Новый собеседник», /start или команда start из payload."""
    lowered = text.strip().lower()
    if lowered in {"начать", "/start", "start", NEW_PARTNER_BTN.lower(), FIND_BTN.lower()}:
        return True
    command = lowered.split()[0].split("@", 1)[0] if lowered else ""
    if command in {"начать", "/start", "start"}:
        return True
    return payload.get("command") == "start"


def _is_report(text: str, payload: dict) -> bool:
    """Кнопка «Пожаловаться» или команда report из payload."""
    if payload.get("command") == "report":
        return True
    return text.strip().lower() in {REPORT_BTN.lower(), "пожаловаться"}


async def stop_active(peer: Peer) -> None:
    """Заканчивает поиск или диалог и ставит «Начать» под текстом."""
    if await chat_api.phase(peer) != "idle":
        await chat_api.stop(peer)
    cancel_search_timeout(peer)
    await gateway.send(peer, STOPPED_TEXT, "main")


async def handle_stop(peer: Peer, text: str, active: bool) -> bool:
    """Заканчивает диалог или поиск и возвращает основное меню."""
    if text.strip().lower() not in {CHAT_BTN_STOP.lower(), STOP_BTN.lower()} or not active:
        return False
    await stop_active(peer)
    return True


async def handle_next(peer: Peer, text: str, searching: bool) -> bool:
    """Кнопка «Следующий собеседник» запускает новый поиск."""
    if text != CHAT_BTN_NEXT:
        return False
    if searching:
        await gateway.send(peer, SEARCHING_TEXT, "line")
        return True
    await connect_with_partner(peer)
    return True


async def handle_chat_line(
    peer: Peer,
    text: str,
    chatting: bool,
    uploader: Callable[[], Awaitable[str]] | None = None,
) -> bool:
    """Пересылает текст и медиа собеседнику."""
    if not chatting:
        return False
    media_state = await uploader() if uploader is not None else "none"
    if media_state == "left":
        await gateway.send(peer, PARTNER_LEFT_TEXT, "partner_left")
        return True
    if text:
        try:
            delivered = (await chat_api.send_message(peer, text)).delivered
        except NotChattingError:
            delivered = False
        if not delivered:
            await gateway.send(peer, PARTNER_LEFT_TEXT, "partner_left")
            return True
    if media_state == "premium":
        await gateway.send(peer, MEDIA_PREMIUM_TEXT, "line")
    return True


async def handle_menu_or_dialog(
    peer: Peer,
    text: str,
    uploader: Callable[[], Awaitable[str]] | None = None,
) -> None:
    """Разбирает меню и реплики диалога."""
    phase = await chat_api.phase(peer)
    chatting = phase == "chatting"
    searching = phase == "searching"

    if await handle_stop(peer, text, chatting or searching):
        return
    if await handle_next(peer, text, searching):
        return
    if await handle_chat_line(peer, text, chatting, uploader):
        return

    await gateway.send_greeting(peer)


async def handle_incoming(
    peer: Peer,
    text: str,
    payload: dict,
    uploader: Callable[[], Awaitable[str]] | None = None,
) -> None:
    """Маршрутизирует сообщение из лички: старт, затем меню или диалог."""
    try:
        await chat_api.visit(peer)
    except ChatApiError as exc:
        print(f"Не записал визит {peer.user_id}: {exc}", flush=True)
    try:
        command = payload.get("command")
        if peer in _awaiting_age:
            age = parse_age(text)
            if age is not None:
                _awaiting_age.discard(peer)
                _age_choice[peer] = age
                await gateway.send(peer, DATING_TEXT, "dating")
                await gateway.send_premium(peer)
                return
            if not command and not _is_start(text, payload):
                await gateway.send(peer, AGE_TEXT, "dating")
                return
            _awaiting_age.discard(peer)
        if _is_start(text, payload):
            await connect_with_partner(peer)
            return
        if command == "dating":
            await handle_dating(peer)
            return
        if command == "dating_find":
            await connect_with_partner(peer)
            return
        if command == "dating_rooms":
            await handle_dating_rooms(peer)
            return
        if command == "dating_settings":
            await handle_dating_settings(peer)
            return
        if command == "main":
            await handle_main_menu(peer)
            return
        if command == "premium":
            await handle_premium(peer)
            return
        if _is_report(text, payload):
            await handle_report(peer)
            return
        await handle_menu_or_dialog(peer, text, uploader)
    except ChatApiError as exc:
        print(f"Chat API недоступен для {peer}: {exc}", flush=True)
        await gateway.send(peer, SERVICE_DOWN_TEXT, "main")


def vk_handler(bot_key: str):
    """Обработчик одного сообщества ВК. Ключ нужен, чтобы ответ ушёл тем же токеном."""

    async def _handle(message: Message) -> None:
        print(
            f"VK входящее group={bot_key} from={message.from_id} peer={message.peer_id}",
            flush=True,
        )
        try:
            if message.from_id is None or message.from_id <= 0:
                return
            text = (message.text or "").strip()
            payload = parse_payload(message.payload)
            peer = Peer(bot_key, message.from_id)
            if message.peer_id != message.from_id:
                await send_vk_greeting(message.ctx_api, message.peer_id)
                if _is_start(text, payload):
                    await connect_with_partner(peer)
                return
            uploader = None
            if message.attachments:

                async def uploader() -> str:
                    return await store_vk_media(message, peer)

            await handle_incoming(peer, text, payload, uploader)
        except Exception as exc:  # noqa: BLE001 — иначе ошибка остаётся только в loguru и в docker её нет
            print(
                f"Ошибка ответа group={bot_key} from={message.from_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    return _handle


async def choose_room(event: MessageEvent, bot_key: str) -> None:
    """Нажатие комнаты: запоминает выбор и переносит галочку в том же сообщении."""
    room = parse_payload(event.payload).get("room")
    if event.user_id is None or event.user_id <= 0 or room not in ROOMS:
        return
    peer = Peer(bot_key, event.user_id)
    _room_choice[peer] = room
    try:
        await event.edit_message(message=ROOMS_TEXT, keyboard=build_rooms_keyboard(room))
    except Exception as exc:  # noqa: BLE001 — клавиатуру можно и не обновить
        print(
            f"Не обновил комнату vk:{bot_key}:{event.user_id}: {type(exc).__name__}: {exc}",
            flush=True,
        )
    try:
        await event.show_snackbar(f"Комната: {ROOMS[room]}")
    except Exception as exc:  # noqa: BLE001
        print(f"Не показал уведомление: {type(exc).__name__}: {exc}", flush=True)


async def choose_gender(event: MessageEvent, bot_key: str) -> None:
    """Нажатие пола: запоминает выбор, обновляет клавиатуру и спрашивает возраст."""
    gender = parse_payload(event.payload).get("value")
    if event.user_id is None or event.user_id <= 0 or gender not in GENDERS:
        return
    peer = Peer(bot_key, event.user_id)
    _gender_choice[peer] = gender
    try:
        await event.edit_message(message=SETTINGS_TEXT, keyboard=build_settings_keyboard(gender))
    except Exception as exc:  # noqa: BLE001 — клавиатуру можно и не обновить
        print(
            f"Не обновил пол vk:{bot_key}:{event.user_id}: {type(exc).__name__}: {exc}",
            flush=True,
        )
    try:
        await event.send_empty_answer()
    except Exception as exc:  # noqa: BLE001
        print(f"Не подтвердил нажатие: {type(exc).__name__}: {exc}", flush=True)
    _awaiting_age.add(peer)
    await gateway.send(peer, AGE_TEXT, "dating")


def vk_start_handler(bot_key: str):
    """Нажатие inline-кнопки: поиск, остановка, жалоба, комната или переход по меню."""

    async def _handle(event: MessageEvent) -> None:
        print(
            f"VK кнопка group={bot_key} from={event.user_id} peer={event.peer_id}",
            flush=True,
        )
        command = parse_payload(event.payload).get("command")
        if command == "room":
            await choose_room(event, bot_key)
            return
        if command == "gender":
            await choose_gender(event, bot_key)
            return
        try:
            await event.send_empty_answer()
        except Exception as exc:  # noqa: BLE001 — ответ на нажатие не должен срывать поиск
            print(f"Не подтвердил нажатие: {type(exc).__name__}: {exc}", flush=True)
        if command not in {"start", "stop", "report", "dating", "dating_find", "premium", "main"}:
            return
        if event.user_id is None or event.user_id <= 0:
            return
        peer = Peer(bot_key, event.user_id)
        try:
            if command in {"start", "dating_find"}:
                await connect_with_partner(peer)
            elif command == "stop":
                await stop_active(peer)
            elif command == "dating":
                await handle_dating(peer)
            elif command == "premium":
                await handle_premium(peer)
            elif command == "main":
                await handle_main_menu(peer)
            else:
                await handle_report(peer)
        except ChatApiError as exc:
            print(f"Chat API недоступен для {peer}: {exc}", flush=True)
            await gateway.send(peer, SERVICE_DOWN_TEXT, "main")
        except Exception as exc:  # noqa: BLE001
            print(
                f"Ошибка кнопки {command} group={bot_key} from={event.user_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    return _handle


def _keyboard_buttons(raw: object) -> bool:
    """У приветствия уже есть кнопки — править его не нужно."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return False
    return isinstance(raw, dict) and bool(raw.get("buttons"))


def _history_attachment(message: dict) -> str | None:
    """Собирает вложения сообщения, чтобы правка текста их не стёрла."""
    parts: list[str] = []
    for item in message.get("attachments") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        body = item.get(kind) if isinstance(kind, str) else None
        if not isinstance(body, dict) or body.get("owner_id") is None or body.get("id") is None:
            continue
        token = f"{kind}{body['owner_id']}_{body['id']}"
        access_key = body.get("access_key")
        parts.append(f"{token}_{access_key}" if access_key else token)
    return ",".join(parts) or None


def _vk_body(response: object) -> dict:
    """Достаёт словарь ответа VK и из обёртки response, и из уже распакованного тела."""
    if not isinstance(response, dict):
        return {}
    nested = response.get("response")
    if "items" not in response and isinstance(nested, dict):
        return nested
    return response


async def answer_waiting(api: Any, bot_key: str) -> None:
    """Отвечает на чужие сообщения за последний час, которые бот ещё не закрыл своим ответом."""
    response = await api.request("messages.getConversations", {"count": 20})
    items = _vk_body(response).get("items")
    if not items:
        print(f"Непрочитанных диалогов нет (group_id={bot_key}).", flush=True)
        return
    cutoff = int(time.time()) - 3600
    for item in items:
        conversation = item.get("conversation") or {}
        last = item.get("last_message") or {}
        peer_id = (conversation.get("peer") or {}).get("id")
        from_id = int(last.get("from_id") or 0)
        if not peer_id or from_id <= 0 or int(last.get("out") or 0) == 1:
            continue
        if int(last.get("date") or 0) < cutoff:
            continue
        await send_vk_greeting(api, peer_id)
        try:
            await api.request("messages.markAsRead", {"peer_id": peer_id})
        except Exception as exc:  # noqa: BLE001
            print(f"Не отметил прочитанным peer={peer_id}: {type(exc).__name__}: {exc}", flush=True)
        print(f"Ответил на ожидающее group={bot_key} peer={peer_id}", flush=True)


async def attach_start_buttons(api: Any, bot_key: str) -> None:
    """Дописывает кнопку «Начать» к свежим приветствиям, которые ушли без неё."""
    response = await api.request("messages.getConversations", {"count": 30})
    items = _vk_body(response).get("items") or []
    for item in items:
        peer_id = ((item.get("conversation") or {}).get("peer") or {}).get("id")
        if not peer_id:
            continue
        history = await api.request("messages.getHistory", {"peer_id": peer_id, "count": 8})
        for message in _vk_body(history).get("items") or []:
            text = message.get("text") or ""
            if int(message.get("out") or 0) != 1 or "Нажми кнопку начать" not in text:
                continue
            if _keyboard_buttons(message.get("keyboard")):
                continue
            edit: dict = {
                "peer_id": peer_id,
                "message": text,
                "keyboard": build_main_keyboard(),
            }
            attachment = _history_attachment(message)
            if attachment:
                edit["attachment"] = attachment
            if message.get("conversation_message_id"):
                edit["conversation_message_id"] = message["conversation_message_id"]
            elif message.get("id"):
                edit["message_id"] = message["id"]
            else:
                break
            try:
                await api.messages.edit(**edit)
            except Exception as exc:  # noqa: BLE001
                print(
                    f"Не добавил кнопку group={bot_key} peer={peer_id}: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
            else:
                print(f"Добавил кнопку Начать group={bot_key} peer={peer_id}", flush=True)
            break


def cancel_search_timeout(peer: Peer) -> None:
    """С поиска уже сняли: найден собеседник или диалог закончен."""
    previous = _search_timeouts.pop(peer, None)
    if previous is not None:
        previous.cancel()


async def _leave_queue_later(peer: Peer) -> None:
    """Через SEARCH_TIMEOUT_SECONDS снимает с поиска, если пара так и не нашлась."""
    try:
        await asyncio.sleep(SEARCH_TIMEOUT_SECONDS)
        if await chat_api.phase(peer) != "searching":
            return
        await chat_api.stop(peer)
        await gateway.send(peer, NO_PARTNERS_TEXT, "main")
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — фоновая задача, иначе ошибка потеряется
        print(f"Не снял с поиска {peer}: {type(exc).__name__}: {exc}", flush=True)
    finally:
        if _search_timeouts.get(peer) is asyncio.current_task():
            del _search_timeouts[peer]


async def handle_dating(peer: Peer) -> None:
    """Кнопка «Чат знакомств»: меняет нижнюю клавиатуру на меню раздела."""
    await gateway.send(peer, DATING_TEXT, "dating")


async def handle_dating_rooms(peer: Peer) -> None:
    """Кнопка «Выбрать комнату»: сообщение с inline-списком комнат."""
    await gateway.send_rooms(peer, peer_room(peer))


async def handle_dating_settings(peer: Peer) -> None:
    """Кнопка «Настроить поиск»: блок с выбором пола собеседника."""
    await gateway.send_settings(peer, _gender_choice.get(peer, ""))


async def handle_main_menu(peer: Peer) -> None:
    """Кнопка «Главное меню»: возвращает нижнюю клавиатуру с поиском."""
    await gateway.send(peer, MENU_TEXT, "line")


async def handle_premium(peer: Peer) -> None:
    """Кнопка «Премиум статус»: картинка акции, список возможностей и кнопка оплаты."""
    await gateway.send_premium(peer)


async def handle_report(peer: Peer) -> None:
    """Жалоба в живом диалоге закрывает его и ищет дальше. После ухода — только подтверждение."""
    phase = await chat_api.phase(peer)
    if phase == "searching":
        await gateway.send(peer, SEARCHING_TEXT, "line")
        return
    if phase != "chatting":
        await gateway.send(peer, REPORT_SENT_TEXT, "partner_left")
        return
    try:
        phase = await chat_api.report(peer)
    except NotChattingError:
        await gateway.send(peer, REPORT_SENT_TEXT, "partner_left")
        return
    await gateway.send(peer, REPORT_SENT_TEXT, "line")
    cancel_search_timeout(peer)
    if phase == "chatting":
        await gateway.send(peer, FOUND_TEXT, "chat")
        return
    await gateway.send(peer, SEARCHING_TEXT, "line")
    _search_timeouts[peer] = asyncio.create_task(_leave_queue_later(peer))


async def connect_with_partner(peer: Peer) -> None:
    """Ставит в поиск. Второй стороне о паре и прежнему собеседнику об уходе пишет Chat API."""
    phase = await chat_api.search(peer)
    await gateway.send(peer, SEARCHING_TEXT, "line")
    cancel_search_timeout(peer)
    if phase == "chatting":
        await gateway.send(peer, FOUND_TEXT, "chat")
        return
    _search_timeouts[peer] = asyncio.create_task(_leave_queue_later(peer))
