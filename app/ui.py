"""Тексты, подписи кнопок и клавиатуры сообщений.

Сами тексты, подписи, списки, раскладка и цвета клавиатур и картинки лежат в app/content/content.json
(редактируются в Bot CRM). Здесь — только сборка клавиатур VK и имена, которые использует код.
"""

from __future__ import annotations

import json
import random
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from vkbottle import Callback, Keyboard, KeyboardButtonColor, OpenLink, Text

from app import content
from app.content import button, items, text

if TYPE_CHECKING:
    from app.premium import PremiumOffer

MENU_TEXT = text("MENU_TEXT")
COMMUNITY_GREETING = text("COMMUNITY_GREETING")
START_BTN = button("START_BTN")

FIND_BTN = button("FIND_BTN")
DATING_BTN = button("DATING_BTN")
PREMIUM_STATUS_BTN = button("PREMIUM_STATUS_BTN")

DATING_FIND_BTN = button("DATING_FIND_BTN")
DATING_ROOMS_BTN = button("DATING_ROOMS_BTN")
DATING_SETTINGS_BTN = button("DATING_SETTINGS_BTN")
MAIN_MENU_BTN = button("MAIN_MENU_BTN")

CHAT_BTN_NEXT = button("CHAT_BTN_NEXT")
CHAT_BTN_STOP = button("CHAT_BTN_STOP")
NEW_PARTNER_BTN = button("NEW_PARTNER_BTN")
PREMIUM_BTN = button("PREMIUM_BTN")
STOP_BTN = button("STOP_BTN")
REPORT_BTN = button("REPORT_BTN")

SEARCHING_TEXT = text("SEARCHING_TEXT")
NO_PARTNERS_TEXT = text("NO_PARTNERS_TEXT")
FOUND_TEXT = text("FOUND_TEXT")
STOPPED_TEXT = text("STOPPED_TEXT")
PARTNER_LEFT_TEXT = text("PARTNER_LEFT_TEXT")
REPORT_SENT_TEXT = text("REPORT_SENT_TEXT")
UNDELIVERED_TEXT = text("UNDELIVERED_TEXT")
SERVICE_DOWN_TEXT = text("SERVICE_DOWN_TEXT")
# Ссылка на оплату уходит только кнопкой OpenLink: из текста ВК соберёт сниппет и сам откроет её.
MEDIA_PREMIUM_TEXT = text("MEDIA_PREMIUM_TEXT")
PARTNER_NO_PREMIUM_TEXT = text("PARTNER_NO_PREMIUM_TEXT")
# Запасная ссылка, если Chat API не выдал личную.
PREMIUM_URL = "https://pay.chatwithyou.site/"
# Тарифы оплаты: (plan, подпись кнопки). Подписи и цены — в content.json, lists.TARIFFS.
TARIFFS: tuple[tuple[str, str], ...] = tuple(items("TARIFFS").items())
# Продление при активном премиуме — без пробного.
RENEW_PLANS = tuple(plan for plan, _ in TARIFFS if plan != "trial")
PREMIUM_ACTIVE_TEXT = text("PREMIUM_ACTIVE_TEXT")
PREMIUM_ACTIVE_UNTIL_TEXT = text("PREMIUM_ACTIVE_UNTIL_TEXT")
PREMIUM_STATUS_TEXT = text("PREMIUM_STATUS_TEXT")
DATING_TEXT = text("DATING_TEXT")
# Раньше здесь были комнаты; имена ROOMS/room оставлены, теперь это города.
ROOMS_TEXT = text("ROOMS_TEXT")
ROOMS: dict[str, str] = items("ROOMS")
# Раскладка городов берётся из клавиатуры ROOMS_KEYBOARD.
ROOM_ROWS = tuple(tuple(cell["item"] for cell in row) for row in content.keyboard("ROOMS_KEYBOARD")["rows"])
DEFAULT_ROOM = "spb"
SETTINGS_TEXT = text("SETTINGS_TEXT")
GENDERS: dict[str, str] = items("GENDERS")
AGE_TEXT = text("AGE_TEXT")
ROOMS_REFRESHED_TOAST = text("ROOMS_REFRESHED_TOAST")
CITY_SELECTED_TOAST = text("CITY_SELECTED_TOAST")

# Цвета content.json -> цвета кнопок ВК. Без цвета — серая кнопка.
_COLORS = {
    "primary": KeyboardButtonColor.PRIMARY,
    "success": KeyboardButtonColor.POSITIVE,
    "danger": KeyboardButtonColor.NEGATIVE,
    "secondary": KeyboardButtonColor.SECONDARY,
}
# Команда в payload для каждой кнопки: по ней обработчики понимают, что нажато.
_BUTTON_COMMANDS = {
    "START_BTN": "start",
    "FIND_BTN": "start",
    "NEW_PARTNER_BTN": "start",
    "DATING_BTN": "dating",
    "PREMIUM_STATUS_BTN": "premium",
    "DATING_FIND_BTN": "dating_find",
    "DATING_ROOMS_BTN": "dating_rooms",
    "DATING_SETTINGS_BTN": "dating_settings",
    "MAIN_MENU_BTN": "main",
    "STOP_BTN": "stop",
    "REPORT_BTN": "report",
}


def _color(cell: dict) -> KeyboardButtonColor:
    return _COLORS.get(cell.get("color"), KeyboardButtonColor.SECONDARY)


def _payload(command: str, **extra: str) -> str:
    return json.dumps({"command": command, **extra})


def _keyboard(name: str, offer: PremiumOffer | None = None) -> str:
    """Клавиатура из content.json: reply — Text-кнопки внизу, inline — Callback под сообщением."""
    kb = content.keyboard(name)
    inline = kb["type"] == "inline"
    keyboard = Keyboard(inline=True) if inline else Keyboard(one_time=False, inline=False)
    for index, row in enumerate(kb["rows"]):
        if index:
            keyboard.row()
        for cell in row:
            key = cell.get("button")
            if key == "PREMIUM_BTN" and offer is not None:
                keyboard = _add_premium_button(keyboard, offer, _color(cell))
                continue
            command = _BUTTON_COMMANDS.get(key or "")
            if command is None:
                raise content.ContentError(f"keyboards.{name}: кнопка {key!r} не поддерживается ботом")
            action = Callback if inline else Text
            keyboard.add(action(content.label(cell), payload=_payload(command)), color=_color(cell))
    return keyboard.get_json()


def format_partner(text: str) -> str:
    """Оформляет реплику так, будто её прислал собеседник."""
    return content.text("PARTNER_MESSAGE").replace("{text}", text)


def city_selected_toast(room: str) -> str:
    """Всплывающая подсказка после выбора города."""
    return CITY_SELECTED_TOAST.replace("{city}", ROOMS[room])


def new_random_id() -> int:
    """Случайный идентификатор messages.send, чтобы VK не склеивал ответы."""
    return random.randint(1, 2_147_483_647)


def build_main_keyboard() -> str:
    """Кнопка «Начать» под текстом. В беседе обычная клавиатура не показывается."""
    return _keyboard("MAIN_KEYBOARD")


def build_bottom_keyboard() -> str:
    """Нижняя клавиатура лички: поиск собеседника, чат знакомств и премиум."""
    return _keyboard("BOTTOM_KEYBOARD")


def build_dating_keyboard() -> str:
    """Нижняя клавиатура раздела «Чат знакомств»: поиск, комнаты, настройки и выход в меню."""
    return _keyboard("DATING_KEYBOARD")


def premium_active_text(offer: PremiumOffer) -> str:
    """«Премиум активен до ДД.ММ.ГГГГ»; без срока — просто «Премиум активен»."""
    if not offer.until_text:
        return PREMIUM_ACTIVE_TEXT
    return PREMIUM_ACTIVE_UNTIL_TEXT.replace("{date}", offer.until_text)


def _add_premium_button(keyboard: Keyboard, offer: PremiumOffer, color: KeyboardButtonColor) -> Keyboard:
    """Кнопка личной ссылки на оплату или, если премиум уже есть, кнопка с его сроком."""
    if offer.active:
        return keyboard.add(
            Callback(premium_active_text(offer), payload=_payload("premium")),
            color=color,
        )
    return keyboard.add(OpenLink(offer.url, PREMIUM_BTN), color=color)


def plan_url(url: str, plan: str) -> str:
    """Добавляет к ссылке оплаты параметр plan, сохраняя существующий query."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "plan"]
    query.append(("plan", plan))
    return urlunsplit(parts._replace(query=urlencode(query)))


def build_premium_keyboard(offer: PremiumOffer) -> str:
    """Inline-кнопки тарифов по раскладке PREMIUM_KEYBOARD. Активному премиуму — только продление без пробного."""
    keyboard = Keyboard(inline=True)
    rows = [
        [cell for cell in row if not offer.active or cell["item"] in RENEW_PLANS]
        for row in content.keyboard("PREMIUM_KEYBOARD")["rows"]
    ]
    for index, row in enumerate(r for r in rows if r):
        if index:
            keyboard.row()
        for cell in row:
            keyboard.add(OpenLink(plan_url(offer.url, cell["item"]), content.label(cell)), color=_color(cell))
    return keyboard.get_json()


def build_rooms_keyboard(selected: str) -> str:
    """Inline-выбор города: выбранный отмечен галочкой."""
    keyboard = Keyboard(inline=True)
    for index, row in enumerate(content.keyboard("ROOMS_KEYBOARD")["rows"]):
        if index:
            keyboard.row()
        for cell in row:
            key = cell["item"]
            label = content.label(cell) + (" ✅" if key == selected else "")
            keyboard.add(Callback(label, payload=_payload("room", room=key)), color=_color(cell))
    return keyboard.get_json()


def build_settings_keyboard(selected: str) -> str:
    """Inline-выбор пола собеседника: выбранный вариант отмечен галочкой."""
    keyboard = Keyboard(inline=True)
    for index, row in enumerate(content.keyboard("SETTINGS_KEYBOARD")["rows"]):
        if index:
            keyboard.row()
        for cell in row:
            key = cell["item"]
            label = content.label(cell) + (" ✅" if key == selected else "")
            keyboard.add(Callback(label, payload=_payload("gender", value=key)), color=_color(cell))
    return keyboard.get_json()


def build_chat_keyboard(offer: PremiumOffer) -> str:
    """Под текстом «комната найдена»: «Новый собеседник», премиум и «Остановить диалог»."""
    return _keyboard("CHAT_KEYBOARD", offer)


def build_partner_left_keyboard() -> str:
    """Под текстом об уходе: синяя «Новый собеседник» и серая «Пожаловаться»."""
    return _keyboard("PARTNER_LEFT_KEYBOARD")
