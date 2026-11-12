"""Тексты, подписи кнопок и клавиатуры сообщений ВК.

Содержимое живёт в flow/flow.yaml; здесь оно только собирается в клавиатуры vkbottle.
Публичные имена (MENU_TEXT, FIND_BTN, ROOMS, build_* …) сохранены для остального кода.
"""

from __future__ import annotations

import json
import random
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from vkbottle import Callback, Keyboard, KeyboardButtonColor, OpenLink, Text

from app import flow
from app.flow import Button, Screen

if TYPE_CHECKING:
    from app.premium import PremiumOffer


def _screen(screen_id: str) -> Screen:
    return flow.get().screen(screen_id)


def _text(key: str, **fmt: object) -> str:
    return flow.get().text(key, **fmt)


def _screen_text(screen_id: str) -> str:
    return _screen(screen_id).text or ""


def _flow_button(screen_id: str, action: str) -> Button:
    """Кнопка экрана по её действию."""
    for row in _screen(screen_id).buttons:
        for button in row:
            if button.action == action:
                return button
    raise flow.FlowError(f"screens.{screen_id}: нет кнопки с action {action!r}")


def _link_button(screen_id: str) -> Button:
    """Первая кнопка-ссылка экрана (личная ссылка оплаты)."""
    for row in _screen(screen_id).buttons:
        for button in row:
            if button.url is not None:
                return button
    raise flow.FlowError(f"screens.{screen_id}: нет кнопки-ссылки")


MENU_TEXT = _screen_text("main")
COMMUNITY_GREETING = _screen_text("start_inline")
START_BTN = _flow_button("start_inline", "start").text

FIND_BTN = _flow_button("main", "start").text
DATING_BTN = _flow_button("main", "dating").text
PREMIUM_STATUS_BTN = _flow_button("main", "premium").text

DATING_FIND_BTN = _flow_button("dating", "dating_find").text
DATING_ROOMS_BTN = _flow_button("dating", "dating_rooms").text
DATING_SETTINGS_BTN = _flow_button("dating", "dating_settings").text
MAIN_MENU_BTN = _flow_button("dating", "main").text

# Кнопки прежней нижней клавиатуры диалога: бот их больше не показывает, но принимает их текст.
CHAT_BTN_NEXT = _flow_button("legacy_keys", "next").text
CHAT_BTN_STOP = _flow_button("legacy_keys", "stop").text
NEW_PARTNER_BTN = _flow_button("chat", "start").text
PREMIUM_BTN = _link_button("chat").text
STOP_BTN = _flow_button("chat", "stop").text
REPORT_BTN = _flow_button("partner_left", "report").text

SEARCHING_TEXT = _text("searching")
NO_PARTNERS_TEXT = _text("no_partners")
FOUND_TEXT = _screen_text("chat")
STOPPED_TEXT = _text("stopped")
PARTNER_LEFT_TEXT = _screen_text("partner_left")
REPORT_SENT_TEXT = _text("report_sent")
UNDELIVERED_TEXT = _screen_text("undelivered")
SERVICE_DOWN_TEXT = _text("service_down")
# Ссылка на оплату уходит только кнопкой OpenLink: из текста ВК соберёт сниппет и сам откроет её.
MEDIA_PREMIUM_TEXT = _text("media_premium")
PARTNER_NO_PREMIUM_TEXT = _text("partner_no_premium")
# Подпись к размытому фото собеседника; кнопка покупки собирается build_keyboard("photo_locked").
PHOTO_LOCKED_TEXT = _screen_text("photo_locked")
# Запасная ссылка, если Chat API не выдал личную.
PREMIUM_URL = _text("premium_url")
# Тарифы оплаты: (plan, подпись кнопки). Страница оплаты по ссылке с plan сразу открывает заказ.
TARIFFS: tuple[tuple[str, str], ...] = tuple(
    (button.plan, button.text) for row in _screen("premium").buttons for button in row if button.plan
)
# Пробный тариф не показывается тому, у кого премиум уже активен: ему остаётся продление.
_TRIAL_PLAN = "trial"
RENEW_PLANS = tuple(plan for plan, _label in TARIFFS if plan != _TRIAL_PLAN)
PREMIUM_ACTIVE_TEXT = _text("premium_active")
PREMIUM_STATUS_TEXT = _screen_text("premium")
DATING_TEXT = _screen_text("dating")
# Раньше здесь были комнаты; имена ROOMS/room оставлены, теперь это города.
ROOMS_TEXT = _screen_text("rooms")
ROOMS: dict[str, str] = dict(_screen("rooms").options.items)
ROOM_ROWS = _screen("rooms").options.rows
DEFAULT_ROOM = _screen("rooms").options.default
SETTINGS_TEXT = _screen_text("settings")
GENDERS: dict[str, str] = dict(_screen("settings").options.items)
AGE_TEXT = _screen_text("age")

# Цвета кнопок ВК. Кнопка без style получает серый: цвет всегда задаётся явно.
_COLORS = {
    "primary": KeyboardButtonColor.PRIMARY,
    "secondary": KeyboardButtonColor.SECONDARY,
    "success": KeyboardButtonColor.POSITIVE,
    "danger": KeyboardButtonColor.NEGATIVE,
}
# Команда кнопки с текущим сроком премиума (action premium из реестра handlers.ACTIONS).
_PREMIUM_COMMAND = "premium"


def format_partner(text: str) -> str:
    """Оформляет реплику так, будто её прислал собеседник."""
    return _text("partner_message", text=text)


def new_random_id() -> int:
    """Случайный идентификатор messages.send, чтобы VK не склеивал ответы."""
    return random.randint(1, 2_147_483_647)


def premium_active_text(offer: PremiumOffer) -> str:
    """«Премиум активен до ДД.ММ.ГГГГ»; без срока — просто «Премиум активен»."""
    if not offer.until_text:
        return PREMIUM_ACTIVE_TEXT
    return _text("premium_active_until", date=offer.until_text)


def plan_url(url: str, plan: str) -> str:
    """Добавляет к ссылке оплаты параметр plan, сохраняя существующий query."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "plan"]
    query.append(("plan", plan))
    return urlunsplit(parts._replace(query=urlencode(query)))


def _color(style: str | None) -> KeyboardButtonColor:
    return _COLORS.get(style or "secondary", KeyboardButtonColor.SECONDARY)


def _assemble(rows: list[list[tuple[Text | Callback | OpenLink, KeyboardButtonColor]]], *, inline: bool) -> str:
    """JSON клавиатуры из рядов (кнопка, цвет)."""
    keyboard = Keyboard(inline=True) if inline else Keyboard(one_time=False, inline=False)
    for index, row in enumerate(rows):
        if index:
            keyboard.row()
        for button, color in row:
            keyboard.add(button, color=color)
    return keyboard.get_json()


def _vk_button(button: Button, *, inline: bool, offer: PremiumOffer | None) -> tuple[Text | Callback | OpenLink, KeyboardButtonColor] | None:
    """Кнопка flow в кнопку ВК. None — в этот раз кнопку не показываем (пробный тариф при активном премиуме)."""
    color = _color(button.style)
    if button.url is not None:
        if offer is not None and offer.active:
            if button.plan == _TRIAL_PLAN:
                return None
            if not button.plan:
                payload = json.dumps({"command": _PREMIUM_COMMAND})
                return Callback(premium_active_text(offer), payload=payload), color
        link = offer.url if offer is not None else PREMIUM_URL
        url = button.url.replace("{premium_url}", link)
        if button.plan:
            url = plan_url(url, button.plan)
        return OpenLink(url, button.text), color
    cls = Callback if inline else Text
    return cls(button.text, payload=button.payload_json()), color


def build_keyboard(screen_id: str, *, offer: PremiumOffer | None = None) -> str | None:
    """Клавиатура экрана из его кнопок. Нет кнопок — None: сообщение уходит без клавиатуры.

    offer нужен кнопкам-ссылкам: личная ссылка вместо {premium_url}; при активном премиуме
    пробный тариф пропускается, а кнопка без тарифа показывает срок премиума.
    """
    screen = _screen(screen_id)
    if screen.options is not None:
        return build_options(screen_id, screen.options.default or "")
    rows = []
    for row in screen.buttons:
        cells = [cell for cell in (_vk_button(b, inline=screen.kind == "inline", offer=offer) for b in row) if cell]
        if cells:
            rows.append(cells)
    if not rows:
        return None
    return _assemble(rows, inline=screen.kind == "inline")


def build_options(screen_id: str, selected: str) -> str:
    """Inline-выбор из options экрана: выбранный вариант отмечен selected_mark."""
    options = _screen(screen_id).options
    mark = f" {options.selected_mark}" if options.selected_mark else ""
    rows = [
        [
            (
                Callback(options.items[key] + (mark if key == selected else ""), payload=options.data(key)),
                _color(options.styles.get(key)),
            )
            for key in row
        ]
        for row in options.rows
    ]
    return _assemble(rows, inline=True)


def uses_premium_link(screen_id: str) -> bool:
    """Есть ли у экрана кнопки с личной ссылкой оплаты."""
    return any(b.url is not None and "{premium_url}" in b.url for row in _screen(screen_id).buttons for b in row)


def build_main_keyboard() -> str:
    """Кнопка «Начать» под текстом. В беседе обычная клавиатура не показывается."""
    return build_keyboard("start_inline")


def build_bottom_keyboard() -> str:
    """Нижняя клавиатура лички: поиск собеседника, чат знакомств и премиум."""
    return build_keyboard("main")


def build_dating_keyboard() -> str:
    """Нижняя клавиатура раздела «Чат знакомств»: поиск, комнаты, настройки и выход в меню."""
    return build_keyboard("dating")


def build_premium_keyboard(offer: PremiumOffer) -> str:
    """Inline-кнопки тарифов, по одной в ряду. Активному премиуму — только продление без пробного."""
    return build_keyboard("premium", offer=offer)


def build_rooms_keyboard(selected: str) -> str:
    """Inline-выбор города: выбранный отмечен галочкой."""
    return build_options("rooms", selected)


def build_settings_keyboard(selected: str) -> str:
    """Inline-выбор пола собеседника: выбранный вариант отмечен галочкой."""
    return build_options("settings", selected)


def build_chat_keyboard(offer: PremiumOffer) -> str:
    """Под текстом «комната найдена»: «Новый собеседник», премиум и «Остановить диалог»."""
    return build_keyboard("chat", offer=offer)


def build_partner_left_keyboard() -> str:
    """Под текстом об уходе: синяя «Новый собеседник» и серая «Пожаловаться»."""
    return build_keyboard("partner_left")
