"""Сбор наблюдаемого поведения бота ВК для теста эквивалентности.

Работает и со старым кодом (константы и клавиатуры в app/ui.py, цепочка if в handlers.py), и с кодом
на flow.yaml: опирается только на публичные имена app.ui, app.handlers, app.gateway и app.events.
Снимок tests/fixtures/ui_snapshot.json снят со старого кода (origin/master 47f1237) командой

    python -c "import json, sys; sys.path.insert(0, 'tests'); import snapshot_collect as s; \
        json.dump(s.collect_all(), open('tests/fixtures/ui_snapshot.json', 'w', encoding='utf-8'), \
        ensure_ascii=False, indent=1, sort_keys=True)"

на коммите до перехода на flow; тест пересобирает то же самое на новом коде и сравнивает.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DEV_MODE", "False")

ROOT = Path(__file__).resolve().parent.parent
PAY_URL = "https://pay.example/x?a=1&plan=z"
PLAIN_URL = "https://pay.chatwithyou.site/"
BOT_KEY = "main"
USER_ID = 7
UNTIL = datetime(2026, 12, 1, 22, tzinfo=timezone.utc)

COMMANDS = [
    "start", "stop", "report", "dating", "dating_find", "dating_rooms", "dating_settings", "main", "premium",
    "room", "gender", "next", "go", "zzz", "",
]


def _offers() -> dict:
    from app.premium import FALLBACK_OFFER, PremiumOffer

    return {
        "inactive": PremiumOffer(PAY_URL),
        "active_date": PremiumOffer(PAY_URL, True, UNTIL),
        "active_naive": PremiumOffer(PAY_URL, True, datetime(2026, 1, 2, 21, 30)),
        "active_forever": PremiumOffer(PAY_URL, True, None),
        "fallback": FALLBACK_OFFER,
    }


def _norm(value, peer=None) -> object:
    if peer is not None and value == peer:
        return "PEER"
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (list, tuple)):
        return [_norm(v, peer) for v in value]
    if isinstance(value, dict):
        return {str(k): _norm(v, peer) for k, v in value.items()}
    return repr(value)


def _calls(mock, peer=None) -> list[list[object]]:
    return [[name, _norm(list(args), peer), _norm(dict(kwargs), peer)] for name, args, kwargs in mock.mock_calls]


def _peer():
    from app.peer import Peer

    return Peer(BOT_KEY, USER_ID)


# ---------------------------------------------------------------- тексты и клавиатуры


def collect_texts() -> dict:
    from app import ui

    result: dict = {}
    for name, value in vars(ui).items():
        if name.isupper() and not name.startswith("_") and isinstance(value, (str, tuple, dict, list)):
            result[name] = json.loads(json.dumps(value, ensure_ascii=False))
    result["__names__"] = sorted(
        name
        for name, value in vars(ui).items()
        if not name.startswith("_")
        and (
            (name.isupper() and isinstance(value, (str, tuple, dict, list)))
            or (inspect.isfunction(value) and value.__module__ == ui.__name__)
        )
    )
    return result


def collect_keyboards() -> dict:
    from app import ui

    offers = _offers()
    result: dict = {
        "main": ui.build_main_keyboard(),
        "bottom": ui.build_bottom_keyboard(),
        "dating": ui.build_dating_keyboard(),
        "partner_left": ui.build_partner_left_keyboard(),
    }
    for name, offer in offers.items():
        result[f"chat:{name}"] = ui.build_chat_keyboard(offer)
        result[f"premium:{name}"] = ui.build_premium_keyboard(offer)
        result[f"active_text:{name}"] = ui.premium_active_text(offer)
    for key in [*ui.ROOMS, "", "zzz"]:
        result[f"rooms:{key}"] = ui.build_rooms_keyboard(key)
    for key in [*ui.GENDERS, "", "zzz"]:
        result[f"settings:{key}"] = ui.build_settings_keyboard(key)
    for url in (PAY_URL, PLAIN_URL, "https://x.y/p?plan=old&b=2#frag"):
        for plan in ("trial", "week"):
            result[f"plan_url:{url}:{plan}"] = ui.plan_url(url, plan)
    return result


def collect_formats() -> dict:
    from app import ui

    return {
        "partner": ui.format_partner("hi"),
        "partner_braces": ui.format_partner("{x} {0}"),
        "partner_empty": ui.format_partner(""),
    }


# ---------------------------------------------------------------- классификация входов


def routing_inputs() -> list[str]:
    """Тексты, на которых сверяется классификация и маршрутизация."""
    return [
        "начать", "Начать", "НАЧАТЬ", "  Начать ", "Начать сейчас", "start", "Start", "/start", "/START", "/start@bot",
        "/Start@Bot x", "start now", "/start payload", "/stop", "/next", "/report", "/search", "/unknown",
        "новый собеседник", "Новый собеседник", "🔍 Новый собеседник", "🔍 новый собеседник",
        "найти собеседника", "Найти собеседника", "🔍 Найти собеседника", "🔍 НАЙТИ СОБЕСЕДНИКА",
        "пожаловаться", "Пожаловаться", "ПОЖАЛОВАТЬСЯ", "🚫 Пожаловаться", "🚫 пожаловаться", "пожаловаться на спам",
        "🛑 Закончить диалог", "🛑 закончить диалог", "Остановить диалог", "остановить диалог", "Закончить диалог",
        "➡️ Следующий собеседник", "Следующий собеседник",
        "привет", "hello world", "26+", "24-34", "26", "17", "100", "", "   ",
        "💘 Чат знакомств", "Чат знакомств", "👑 Премиум статус", "Премиум статус", "💎 Купить премиум",
        "🔥 Пошлый чат", "❤️ Найти девушку", "📍 Выбрать город", "🌍 Выбрать комнату", "⚙️ Настроить поиск",
        "◀️ Главное меню", "Главное меню", "👑 Премиум активен", "Москва", "Нажми кнопку начать",
    ]


def collect_classification(inputs: list[str] | None = None) -> dict:
    from app import handlers as h

    texts = list(dict.fromkeys(inputs if inputs is not None else routing_inputs()))
    result = {}
    for text in texts:
        for command in (None, *COMMANDS):
            payload = {} if command is None else {"command": command}
            result[f"{text!r}|{command}"] = [h._is_start(text, payload), h._is_report(text, payload)]
    result["payload_extra"] = [
        h._is_start("", {"command": "start", "x": 1}),
        h._is_report("", {"command": "report", "x": 1}),
        h._is_start("", {"command": ["start"]}),
    ]
    return result


def collect_parse() -> dict:
    from app import handlers as h

    result = {}
    for raw in (None, "", "{}", '{"command": "start"}', '{"command": "room", "room": "msk"}', "[1]", "not json",
                {"command": "stop"}, {}, 5, b"x"):
        result[repr(raw)] = h.parse_payload(raw)
    for text in ("26", "26+", "24-34", "24 - 34", "26 лет", "13", "100", "34-24", "abc", "", "99+", "14", "1-2"):
        result[f"age:{text}"] = h.parse_age(text)
    return result


# ---------------------------------------------------------------- handlers: сообщения


def _make_api(phase: str, mode: str) -> MagicMock:
    from app.api_client import ChatApiError

    api = MagicMock()
    api.visit = AsyncMock()
    api.phase = AsyncMock(return_value=phase)
    api.search = AsyncMock(return_value="chatting" if mode == "B" else "searching")
    api.stop = AsyncMock(return_value=SimpleNamespace(was_active=True, promo=False))
    api.report = AsyncMock(return_value="chatting" if mode == "B" else "searching")
    api.send_message = AsyncMock(return_value=SimpleNamespace(delivered=mode != "F"))
    api.delivery_failed = AsyncMock()
    if mode == "E":
        for name in ("search", "stop", "report", "send_message"):
            getattr(api, name).side_effect = ChatApiError("down")
    if mode == "V":
        api.visit.side_effect = ChatApiError("down")
    return api


def _offer_for(mode: str):
    offers = _offers()
    return offers["active_date"] if mode == "C" else offers["inactive"]


async def _settle(h) -> None:
    await asyncio.sleep(0)
    for task in list(h._search_timeouts.values()):
        task.cancel()
    await asyncio.gather(*h._search_timeouts.values(), return_exceptions=True)
    h._search_timeouts.clear()


async def _run_incoming(
    text: str, payload: dict, phase: str, awaiting: bool, mode: str, uploader_state: str | None = None
) -> dict:
    from app import handlers as h

    peer = _peer()
    h._awaiting_age.clear()
    h._age_choice.clear()
    if awaiting:
        h._awaiting_age.add(peer)
    gw = AsyncMock()
    api = _make_api(phase, mode)
    uploader = None
    if uploader_state is not None:

        async def uploader() -> str:
            return uploader_state

    with patch.object(h, "gateway", gw), patch.object(h, "chat_api", api), patch.object(
        h, "premium_offer", AsyncMock(return_value=_offer_for(mode))
    ):
        await h.handle_incoming(peer, text, payload, uploader)
        await _settle(h)
    return {
        "gateway": _calls(gw, peer),
        "api": _calls(api, peer),
        "awaiting_after": peer in h._awaiting_age,
        "age_after": h._age_choice.get(peer),
    }


async def collect_incoming(inputs: list[str] | None = None) -> dict:
    from app import handlers as h

    texts = list(dict.fromkeys(inputs if inputs is not None else routing_inputs()))
    h._room_choice.clear()
    h._gender_choice.clear()
    result = {}
    for text in texts:
        for phase in ("idle", "searching", "chatting"):
            for awaiting in (False, True):
                for mode in ("A", "B", "C"):
                    result[f"{text}|{phase}|{int(awaiting)}|{mode}"] = await _run_incoming(
                        text, {}, phase, awaiting, mode
                    )
    # payload каждой команды с пустым и «обычным» текстом, во всех фазах.
    for command in COMMANDS:
        for text in ("", "привет", "Начать"):
            for phase in ("idle", "searching", "chatting"):
                for awaiting in (False, True):
                    for mode in ("A", "B", "C"):
                        key = f"payload:{command}|{text}|{phase}|{int(awaiting)}|{mode}"
                        result[key] = await _run_incoming(text, {"command": command}, phase, awaiting, mode)
    # Возраст, ошибки Chat API, недоставка, медиа.
    for text in ("26", "26+", "24-34", "abc", "Начать"):
        for mode in ("A", "E", "V", "C"):
            result[f"age:{text}|{mode}"] = await _run_incoming(text, {}, "idle", True, mode)
    for text in ("Начать", "привет", "Пожаловаться", "Остановить диалог", "➡️ Следующий собеседник"):
        for phase in ("idle", "searching", "chatting"):
            for mode in ("E", "V", "F"):
                result[f"mode:{text}|{phase}|{mode}"] = await _run_incoming(text, {}, phase, False, mode)
    for state in ("none", "ok", "left", "premium", "partner_premium", "failed"):
        for text in ("", "hi"):
            for mode in ("A", "F"):
                result[f"media:{state}|{text}|{mode}"] = await _run_incoming(text, {}, "chatting", False, mode, state)
    return result


class _CtxApi:
    def __repr__(self) -> str:
        return "CTX_API"


def _message(text: str, payload, *, peer_id: int = USER_ID, from_id: int | None = USER_ID, attachments=None):
    return SimpleNamespace(
        text=text,
        payload=payload,
        from_id=from_id,
        peer_id=peer_id,
        attachments=attachments,
        ctx_api=_CtxApi(),
    )


async def collect_vk_handler() -> dict:
    """Входящее сообщение целиком: личка, беседа, чужие отправители, вложения."""
    from app import handlers as h

    cases = {
        "dm_text": _message("Начать", None),
        "dm_payload_str": _message("", json.dumps({"command": "dating"})),
        "dm_payload_dict": _message("", {"command": "premium"}),
        "dm_chat_line": _message("  привет  ", None),
        "dm_bad_payload": _message("привет", "not json"),
        "group_start": _message("Начать", None, peer_id=2_000_000_001),
        "group_start_slash": _message("/start@bot", None, peer_id=2_000_000_001),
        "group_payload_start": _message("", {"command": "start"}, peer_id=2_000_000_001),
        "group_text": _message("привет", None, peer_id=2_000_000_001),
        "no_from": _message("Начать", None, from_id=None),
        "bot_from": _message("Начать", None, from_id=-5),
        "attachment": _message("фото", None, attachments=[object()]),
    }
    result = {}
    for name, message in cases.items():
        for phase in ("idle", "chatting"):
            h._awaiting_age.clear()
            gw = AsyncMock()
            greeting = AsyncMock()
            api = _make_api(phase, "A")
            with patch.object(h, "gateway", gw), patch.object(h, "chat_api", api), patch.object(
                h, "send_vk_greeting", greeting
            ), patch.object(h, "store_vk_media", AsyncMock(return_value="ok")), patch.object(
                h, "premium_offer", AsyncMock(return_value=_offers()["inactive"])
            ), contextlib.redirect_stdout(io.StringIO()):
                await h.vk_handler(BOT_KEY)(message)
                await _settle(h)
            result[f"{name}|{phase}"] = {
                "gateway": _calls(gw, _peer()),
                "greeting": _norm(greeting.mock_calls, _peer()),
                "api": _calls(api, _peer()),
            }
    return result


# ---------------------------------------------------------------- handlers: нажатия inline-кнопок


def _event(payload, user_id: int | None = USER_ID, fail: str | None = None) -> MagicMock:
    event = MagicMock()
    event.payload = payload
    event.user_id = user_id
    event.peer_id = user_id
    event.edit_message = AsyncMock()
    event.show_snackbar = AsyncMock()
    event.send_empty_answer = AsyncMock()
    if fail:
        getattr(event, fail).side_effect = RuntimeError("vk")
    return event


def _event_dump(event, gw, api, peer) -> dict:
    return {
        "edit": [dict(c.kwargs) for c in event.edit_message.call_args_list],
        "snackbar": _norm([list(c.args) for c in event.show_snackbar.call_args_list]),
        "empty_answers": len(event.send_empty_answer.call_args_list),
        "gateway": _calls(gw, peer),
        "api": _calls(api, peer),
    }


async def _run_event(payload, *, user_id: int | None = USER_ID, phase: str = "idle", mode: str = "A", fail=None) -> dict:
    from app import handlers as h

    peer = _peer()
    h._awaiting_age.clear()
    event = _event(payload, user_id, fail)
    gw = AsyncMock()
    api = _make_api(phase, mode)
    with patch.object(h, "gateway", gw), patch.object(h, "chat_api", api), patch.object(
        h, "premium_offer", AsyncMock(return_value=_offer_for(mode))
    ), contextlib.redirect_stdout(io.StringIO()):
        await h.vk_start_handler(BOT_KEY)(event)
        await _settle(h)
    entry = _event_dump(event, gw, api, peer)
    entry["awaiting"] = peer in h._awaiting_age
    return entry


async def collect_events_buttons() -> dict:
    from app import handlers as h
    from app.ui import GENDERS, ROOMS

    result = {}
    h._room_choice.clear()
    h._gender_choice.clear()
    for command in COMMANDS:
        for phase in ("idle", "searching", "chatting"):
            for mode in ("A", "B", "C", "E"):
                for as_text in (False, True):
                    payload = {"command": command}
                    payload = json.dumps(payload) if as_text else payload
                    result[f"cmd:{command}|{phase}|{mode}|{int(as_text)}"] = await _run_event(
                        payload, phase=phase, mode=mode
                    )
    for user_id in (None, 0, -3):
        for command in ("start", "room", "gender", "stop"):
            result[f"user:{user_id}|{command}"] = await _run_event({"command": command, "room": "msk", "value": "male"}, user_id=user_id)
    for payload in (None, "", "garbage", "[]", 5):
        result[f"raw:{payload!r}"] = await _run_event(payload)
    for fail in ("send_empty_answer",):
        result[f"fail:{fail}"] = await _run_event({"command": "start"}, fail=fail)
    for room in [*ROOMS, "talk", "", None]:
        for fail in (None, "edit_message", "show_snackbar"):
            h._room_choice.clear()
            result[f"room:{room}|{fail}"] = await _run_event({"command": "room", "room": room}, fail=fail)
    for gender in [*GENDERS, "x", "", None]:
        for fail in (None, "edit_message", "send_empty_answer"):
            h._gender_choice.clear()
            result[f"gender:{gender}|{fail}"] = await _run_event({"command": "gender", "value": gender}, fail=fail)
    # Выбранные город и пол показываются при повторном открытии экранов.
    for room, gender in (("msk", "male"), ("any", "female")):
        h._room_choice.clear()
        h._gender_choice.clear()
        await _run_event({"command": "room", "room": room})
        await _run_event({"command": "gender", "value": gender})
        result[f"after:{room}:{gender}"] = {
            "rooms": await _run_incoming("", {"command": "dating_rooms"}, "idle", False, "A"),
            "settings": await _run_incoming("", {"command": "dating_settings"}, "idle", False, "A"),
            "peer_room": h.peer_room(_peer()),
        }
    h._room_choice.clear()
    h._gender_choice.clear()
    h._awaiting_age.clear()
    return result


# ---------------------------------------------------------------- приветствия в истории (attach_start_buttons)


def _history_api(conversations, histories, edit_fail: bool = False) -> MagicMock:
    api = MagicMock()

    async def request(method: str, params: dict | None = None):
        if method == "messages.getConversations":
            return conversations
        if method == "messages.getHistory":
            return histories.get((params or {}).get("peer_id"), {"items": []})
        return {}

    api.request = AsyncMock(side_effect=request)
    api.messages.edit = AsyncMock(side_effect=RuntimeError("vk") if edit_fail else None)
    return api


def _conv(peer_id: int, **last) -> dict:
    return {"conversation": {"peer": {"id": peer_id}}, "last_message": last}


async def collect_history() -> dict:
    import time

    from app import handlers as h

    now = int(time.time())
    marker = "Привет!\nНажми кнопку начать"
    keyboard_on = json.dumps({"buttons": [[{"action": {"type": "text", "label": "x"}}]]})
    cases = {
        "marker_plain": {"items": [{"out": 1, "text": marker, "id": 5}]},
        "marker_cmid": {"items": [{"out": 1, "text": marker, "conversation_message_id": 9, "id": 5}]},
        "marker_keyboard_dict": {"items": [{"out": 1, "text": marker, "id": 5, "keyboard": {"buttons": [[1]]}}]},
        "marker_keyboard_str": {"items": [{"out": 1, "text": marker, "id": 5, "keyboard": keyboard_on}]},
        "marker_keyboard_empty": {"items": [{"out": 1, "text": marker, "id": 5, "keyboard": {"buttons": []}}]},
        "marker_keyboard_bad": {"items": [{"out": 1, "text": marker, "id": 5, "keyboard": "{"}]},
        "marker_attachments": {
            "items": [
                {
                    "out": 1,
                    "text": marker,
                    "id": 5,
                    "attachments": [
                        {"type": "photo", "photo": {"owner_id": -1, "id": 2, "access_key": "k"}},
                        {"type": "photo", "photo": {"owner_id": -1, "id": 3}},
                        {"type": "photo", "photo": {"owner_id": -1}},
                        "junk",
                    ],
                }
            ]
        },
        "marker_no_ids": {"items": [{"out": 1, "text": marker}]},
        "marker_incoming": {"items": [{"out": 0, "text": marker, "id": 5}]},
        "marker_other_text": {"items": [{"out": 1, "text": "Нажми кнопку", "id": 5}]},
        "marker_wrapped": {"response": {"items": [{"out": 1, "text": marker, "id": 5}]}},
        "marker_second": {"items": [{"out": 1, "text": "x", "id": 4}, {"out": 1, "text": marker, "id": 5}]},
        "empty": {"items": []},
    }
    result = {}
    for name, history in cases.items():
        for edit_fail in (False, True):
            api = _history_api({"items": [_conv(11), _conv(0), {"conversation": {}}]}, {11: history}, edit_fail)
            with contextlib.redirect_stdout(io.StringIO()):
                await h.attach_start_buttons(api, BOT_KEY)
            result[f"{name}|{int(edit_fail)}"] = {
                "requests": _norm([list(c.args) for c in api.request.call_args_list]),
                "edits": _norm([dict(c.kwargs) for c in api.messages.edit.call_args_list]),
            }
    waiting = {
        "recent": {"items": [_conv(21, from_id=21, out=0, date=now - 10)]},
        "old": {"items": [_conv(22, from_id=22, out=0, date=now - 7200)]},
        "out": {"items": [_conv(23, from_id=23, out=1, date=now - 10)]},
        "bot": {"items": [_conv(24, from_id=-24, out=0, date=now - 10)]},
        "none": {"items": []},
        "wrapped": {"response": {"items": [_conv(25, from_id=25, out=0, date=now - 10)]}},
    }
    for name, conversations in waiting.items():
        api = _history_api(conversations, {})
        greeting = AsyncMock()
        with patch.object(h, "send_vk_greeting", greeting), contextlib.redirect_stdout(io.StringIO()):
            await h.answer_waiting(api, BOT_KEY)
        result[f"waiting:{name}"] = {
            "greeting": [[c.args[1]] for c in greeting.call_args_list],
            "requests": _norm([list(c.args) for c in api.request.call_args_list]),
        }
    return result


# ---------------------------------------------------------------- gateway: что уходит в VK


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _gateway_env(send_side_effect=None, upload_fail: bool = False):
    """Gateway с подделкой VK API: записывает messages.send и загрузки файлов."""
    from app import gateway as gw_mod

    api = MagicMock()
    api.messages.send = AsyncMock(side_effect=send_side_effect, return_value=1)
    uploads: list = []

    async def fake_attachment(_api, peer_id, kind, content_type, data):
        uploads.append([peer_id, kind, content_type, len(data), _sha(data)])
        if upload_fail:
            raise RuntimeError("upload")
        return f"att:{kind}:{_sha(data)[:12]}"

    gateway = gw_mod.Gateway()
    gateway.add(BOT_KEY, api)
    return gw_mod, gateway, api, uploads


def _sent(api) -> list:
    return [_norm(dict(c.kwargs)) for c in api.messages.send.call_args_list]


async def collect_gateway() -> dict:
    offers = _offers()
    peer = _peer()
    result: dict = {}

    async def run(name: str, fn, *, offer=None, send_side_effect=None, upload_fail=False, unknown_peer=False):
        gw_mod, gateway, api, uploads = _gateway_env(send_side_effect, upload_fail)
        premium = AsyncMock(return_value=offer if offer is not None else offers["inactive"])
        target = _peer() if not unknown_peer else _peer().__class__("other", USER_ID)
        with patch.object(gw_mod, "_vk_attachment", fake_attachment_proxy(uploads, upload_fail)), patch.object(
            gw_mod, "new_random_id", lambda: 1
        ), patch.object(gw_mod, "premium_offer", premium), contextlib.redirect_stdout(io.StringIO()):
            returned = await fn(gateway, target)
        result[name] = {
            "returned": returned,
            "sent": _sent(api),
            "uploads": uploads,
            "premium_calls": _calls(premium, peer),
        }

    def fake_attachment_proxy(uploads, upload_fail):
        async def fake(_api, peer_id, kind, content_type, data):
            uploads.append([peer_id, kind, content_type, len(data), _sha(data)])
            if upload_fail:
                raise RuntimeError("upload")
            return f"att:{kind}:{_sha(data)[:12]}"

        return fake

    for kind in ("main", "line", "chat", "partner_left", "dating", "premium", "zzz", ""):
        for name, offer in offers.items():
            await run(f"send:{kind}:{name}", lambda g, p, k=kind: g.send(p, "тест", k), offer=offer)
    await run("send:no_api", lambda g, p: g.send(p, "тест", "line"), unknown_peer=True)
    await run("send:keyboard_rejected", lambda g, p: g.send(p, "тест", "line"), send_side_effect=[RuntimeError("kb"), 2])
    await run("send:all_rejected", lambda g, p: g.send(p, "тест", "line"), send_side_effect=RuntimeError("down"))
    await run("greeting", lambda g, p: g.send_greeting(p))
    await run("greeting:upload_fail", lambda g, p: g.send_greeting(p), upload_fail=True)
    await run("greeting:no_api", lambda g, p: g.send_greeting(p), unknown_peer=True)
    await run("greeting:rejected", lambda g, p: g.send_greeting(p), send_side_effect=[RuntimeError("kb"), 2])
    for selected in ("", "spb", "any", "zzz"):
        await run(f"rooms:{selected}", lambda g, p, s=selected: g.send_rooms(p, s))
    for selected in ("", "male", "any", "zzz"):
        await run(f"settings:{selected}", lambda g, p, s=selected: g.send_settings(p, s))
    await run("rooms:no_api", lambda g, p: g.send_rooms(p, ""), unknown_peer=True)
    for name, offer in offers.items():
        await run(f"premium:{name}", lambda g, p, o=offer: g.send_premium(p, o))
        await run(f"premium_none:{name}", lambda g, p: g.send_premium(p), offer=offer)
        await run(f"premium:{name}:upload_fail", lambda g, p, o=offer: g.send_premium(p, o), upload_fail=True)
        await run(f"media_premium:{name}", lambda g, p: g.send_media_premium(p), offer=offer)
        await run(f"media_premium_partner:{name}", lambda g, p: g.send_media_premium(p, partner=True), offer=offer)
    await run("premium:no_api", lambda g, p: g.send_premium(p, offers["inactive"]), unknown_peer=True)
    await run("media_premium:no_api", lambda g, p: g.send_media_premium(p), unknown_peer=True)
    for kind, content_type, data in (
        ("photo", "image/jpeg", b"x"),
        ("voice", "audio/ogg", b"yy"),
        ("video", "video/mp4", b"zzz"),
    ):
        await run(f"media:{kind}", lambda g, p, a=(kind, content_type, data): g.send_media(p, *a))
        await run(f"media:{kind}:upload_fail", lambda g, p, a=(kind, content_type, data): g.send_media(p, *a), upload_fail=True)
    await run("media:blocked", lambda g, p: g.send_media(p, "photo", "image/jpeg", b"x"), send_side_effect=RuntimeError("[901] blocked"))
    await run("media:no_api", lambda g, p: g.send_media(p, "photo", "image/jpeg", b"x"), unknown_peer=True)
    await run("notice:text", lambda g, p: g.send_notice(p, "ув", photo=None, content_type=None))
    await run("notice:photo", lambda g, p: g.send_notice(p, "ув", photo=b"img", content_type="image/png"))
    await run("notice:photo_default_type", lambda g, p: g.send_notice(p, "ув", photo=b"img", content_type=None))
    await run("notice:photo_upload_fail", lambda g, p: g.send_notice(p, "ув", photo=b"img", content_type=None), upload_fail=True)
    await run(
        "notice:photo_blocked",
        lambda g, p: g.send_notice(p, "ув", photo=b"img", content_type=None),
        send_side_effect=RuntimeError("[7] blocked"),
    )
    await run("notice:no_api", lambda g, p: g.send_notice(p, "ув", photo=b"img", content_type=None), unknown_peer=True)
    return result


async def collect_greeting_functions() -> dict:
    """Функции send_vk_* напрямую: баннеры и тексты без обёртки Gateway."""
    offers = _offers()
    result = {}
    for name, offer in offers.items():
        gw_mod, _gateway, api, uploads = _gateway_env()

        async def fake(_api, peer_id, kind, content_type, data, uploads=uploads):
            uploads.append([peer_id, kind, content_type, len(data), _sha(data)])
            return f"att:{kind}"

        with patch.object(gw_mod, "_vk_attachment", fake), patch.object(gw_mod, "new_random_id", lambda: 1), patch.object(
            gw_mod, "premium_offer", AsyncMock(return_value=offer)
        ):
            await gw_mod.send_vk_greeting(api, USER_ID)
            await gw_mod.send_vk_premium(api, _peer(), offer)
        result[name] = {"sent": _sent(api), "uploads": uploads}
    return result


# ---------------------------------------------------------------- события Chat API


async def collect_events() -> dict:
    from app import events as ev
    from app.api_client import ChatApiError

    peer = _peer()
    to = {"bot_key": BOT_KEY, "user_id": USER_ID}
    bodies = {
        "partner_found": {"type": "partner_found", "to": to},
        "message": {"type": "message", "to": to, "text": "hello {x}"},
        "message_empty": {"type": "message", "to": to},
        "partner_left": {"type": "partner_left", "to": to},
        "undeliverable": {"type": "partner_left", "to": to, "reason": "undeliverable"},
        "other_reason": {"type": "partner_left", "to": to, "reason": "left"},
        "media": {"type": "media", "to": to, "media_id": "m1"},
        "media_no_id": {"type": "media", "to": to},
        "unknown": {"type": "zzz", "to": to},
    }
    result = {}
    for name, body in bodies.items():
        for ok in (True, False):
            for fetch in ("ok", "error"):
                for fail_report in (False, True):
                    gw = AsyncMock()
                    gw.send = AsyncMock(return_value=ok)
                    gw.send_media = AsyncMock(return_value=ok)
                    api = MagicMock()
                    api.delivery_failed = AsyncMock(side_effect=ChatApiError("x") if fail_report else None)
                    api.fetch_media = AsyncMock(
                        side_effect=ChatApiError("x") if fetch == "error" else None,
                        return_value=(b"data", "image/jpeg", "photo"),
                    )
                    cancel = MagicMock()
                    with patch.object(ev, "gateway", gw), patch.object(ev, "chat_api", api), patch.object(
                        ev, "cancel_search_timeout", cancel
                    ), contextlib.redirect_stdout(io.StringIO()):
                        await ev._deliver(body)
                    result[f"{name}:{int(ok)}:{fetch}:{int(fail_report)}"] = {
                        "gateway": _calls(gw, peer),
                        "failed": _calls(api.delivery_failed, peer),
                        "fetch": _calls(api.fetch_media),
                        "cancel": _norm(cancel.mock_calls, peer),
                    }
    notices = {
        "notice": {"type": "notice", "to": to, "text": "  привет  "},
        "notice_photo": {"type": "notice", "to": to, "text": "привет", "media_id": "m2"},
        "notice_empty": {"type": "notice", "to": to, "text": " "},
        "notice_other": {"type": "x", "to": to, "text": "t"},
        "notice_no_to": {"type": "notice", "text": "t"},
    }
    for name, body in notices.items():
        for photo in (None, (b"img", "image/jpeg")):
            gw = AsyncMock()
            with patch.object(ev, "gateway", gw), patch.object(ev, "_NOTICE_INTERVAL", 0), patch.object(
                ev, "_notice_photo", AsyncMock(return_value=photo or (None, None))
            ):
                await ev._deliver_notice(body)
            result[f"{name}:{int(photo is not None)}"] = {"gateway": _calls(gw, peer)}
    for kind in ("photo", "video"):
        for fetch_error in (False, True):
            api = MagicMock()
            api.fetch_media = AsyncMock(
                side_effect=ChatApiError("x") if fetch_error else None, return_value=(b"d", "image/png", kind)
            )
            with patch.object(ev, "chat_api", api), contextlib.redirect_stdout(io.StringIO()):
                result[f"notice_photo:{kind}:{int(fetch_error)}"] = _norm(await ev._notice_photo({"media_id": "m"}))
    with contextlib.redirect_stdout(io.StringIO()):
        result["notice_photo:none"] = _norm(await ev._notice_photo({}))
    return result


# ---------------------------------------------------------------- всё вместе


def collect_all(*, inputs: list[str] | None = None) -> dict:
    """Весь снимок. inputs — список текстов (при сравнении берётся из снимка, чтобы набор совпал)."""
    with contextlib.redirect_stdout(io.StringIO()):
        snapshot = {
            "texts": collect_texts(),
            "keyboards": collect_keyboards(),
            "formats": collect_formats(),
            "classification": collect_classification(inputs),
            "parse": collect_parse(),
            "incoming": asyncio.run(collect_incoming(inputs)),
            "vk_handler": asyncio.run(collect_vk_handler()),
            "buttons": asyncio.run(collect_events_buttons()),
            "history": asyncio.run(collect_history()),
            "gateway": asyncio.run(collect_gateway()),
            "senders": asyncio.run(collect_greeting_functions()),
            "events": asyncio.run(collect_events()),
        }
    return json.loads(json.dumps(snapshot, ensure_ascii=False))
