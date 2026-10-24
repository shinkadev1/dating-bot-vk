"""Тексты, подписи кнопок и клавиатуры сообщений."""

import json
import random

from vkbottle import Callback, Keyboard, KeyboardButtonColor, OpenLink, Text

MENU_TEXT = "Найди собеседника прямо сейчас"
COMMUNITY_GREETING = (
    "👋 Привет! Это чат для анонимных знакомств, флирта и легкого общения\n"
    "Найди собеседника прямо сейчас. Нажми кнопку начать"
)
START_BTN = "Начать"

FIND_BTN = "🔍 Найти собеседника"
DATING_BTN = "💘 Чат знакомств"
PREMIUM_STATUS_BTN = "👑 Премиум статус"

DATING_FIND_BTN = "❤️ Найти девушку"
DATING_ROOMS_BTN = "🌍 Выбрать комнату"
DATING_SETTINGS_BTN = "⚙️ Настроить поиск"
MAIN_MENU_BTN = "◀️ Главное меню"

CHAT_BTN_NEXT = "➡️ Следующий собеседник"
CHAT_BTN_STOP = "🛑 Закончить диалог"
NEW_PARTNER_BTN = "🔍 Новый собеседник"
PREMIUM_BTN = "💎 Купить премиум"
STOP_BTN = "Остановить диалог"
REPORT_BTN = "🚫 Пожаловаться"

SEARCHING_TEXT = "🔎 Ищем собеседника..."
NO_PARTNERS_TEXT = "Сейчас собеседников нет, приходите чуть позже 😔"
FOUND_TEXT = "Комната 💬 найдена. Общайтесь!"
STOPPED_TEXT = f"{MENU_TEXT}\n\nДиалог остановлен. Нажми «Начать», чтобы начать снова."
PARTNER_LEFT_TEXT = (
    "Собеседник закончил диалог 😔\n\n"
    "Пожалуйста, нажмите Пожаловаться, если встретили спам."
)
REPORT_SENT_TEXT = "Жалоба отправлена. Спасибо, что сообщили."
UNDELIVERED_TEXT = "❌ Собеседник недоступен, диалог закончен.\nНажми «Начать», чтобы найти нового собеседника."
SERVICE_DOWN_TEXT = "Сервис временно недоступен. Попробуй через минуту."
MEDIA_PREMIUM_TEXT = (
    "Чтобы отправлять медиа, получите премиум:\n"
    "https://vk.ru/club242172702"
)
PREMIUM_URL = "https://clck.su/cDapp"
PREMIUM_STATUS_TEXT = (
    "⚡ Временная акция, скидка 99%:\n\n"
    "🍓 Настройка поиска: например, только девушки младше 25 лет\n"
    "💋 Комнаты для общения по тематике: флирт, знакомства\n"
    "📹 Отправка и получение любых фото, видео и голосовых без ограничений\n"
    "🔝 Первое место в поиске\n"
    "🚫 Никакой рекламы"
)
DATING_TEXT = "👑 Для продолжения нужен Премиум"
ROOMS_TEXT = "✌️ Выберите комнату, в которой хотите искать собеседников:"
ROOMS: dict[str, str] = {
    "spb": "Встречи в г. Санкт-Петербург",
    "talk": "Общение",
    "photo": "Обмен фото",
    "voice": "Голоса",
    "naughty": "Пошлый",
    "dating": "Знакомства",
}
ROOM_ROWS = (("spb",), ("talk", "photo"), ("voice", "naughty"), ("dating",))
DEFAULT_ROOM = "spb"
SETTINGS_TEXT = (
    "💎 Только для Премиум-пользователей\n\n"
    "👱‍♀️👱 Пожалуйста, выберите желаемый пол собеседника:\n\n"
    "🔍 Бот будет искать собеседников только с заданными параметрами поиска"
)
GENDERS: dict[str, str] = {
    "female": "👱‍♀️ Женский",
    "male": "👱‍♂️ Мужской",
    "any": "Не важно",
}
AGE_TEXT = (
    "✏️ Введите желаемый возраст собеседника\n\n"
    "ℹ️ Вы можете настроить поиск \"от 26\" введя \"26+\", "
    "или указать диапазон поиска, например, \"24-34\""
)


def format_partner(text: str) -> str:
    """Оформляет реплику так, будто её прислал собеседник."""
    return f"👤 Собеседник:\n{text}"


def new_random_id() -> int:
    """Случайный идентификатор messages.send, чтобы VK не склеивал ответы."""
    return random.randint(1, 2_147_483_647)


def build_main_keyboard() -> str:
    """Кнопка «Начать» под текстом. В беседе обычная клавиатура не показывается."""
    keyboard = Keyboard(inline=True).add(
        Callback(START_BTN, payload=json.dumps({"command": "start"})),
        color=KeyboardButtonColor.POSITIVE,
    )
    return keyboard.get_json()


def build_bottom_keyboard() -> str:
    """Нижняя клавиатура лички: поиск собеседника, чат знакомств и премиум."""
    keyboard = (
        Keyboard(one_time=False, inline=False)
        .add(
            Text(FIND_BTN, payload=json.dumps({"command": "start"})),
            color=KeyboardButtonColor.PRIMARY,
        )
        .add(
            Text(DATING_BTN, payload=json.dumps({"command": "dating"})),
            color=KeyboardButtonColor.PRIMARY,
        )
        .row()
        .add(
            Text(PREMIUM_STATUS_BTN, payload=json.dumps({"command": "premium"})),
            color=KeyboardButtonColor.POSITIVE,
        )
    )
    return keyboard.get_json()


def build_dating_keyboard() -> str:
    """Нижняя клавиатура раздела «Чат знакомств»: поиск, комнаты, настройки и выход в меню."""
    keyboard = (
        Keyboard(one_time=False, inline=False)
        .add(
            Text(DATING_FIND_BTN, payload=json.dumps({"command": "dating_find"})),
            color=KeyboardButtonColor.PRIMARY,
        )
        .add(
            Text(DATING_ROOMS_BTN, payload=json.dumps({"command": "dating_rooms"})),
            color=KeyboardButtonColor.PRIMARY,
        )
        .row()
        .add(
            Text(DATING_SETTINGS_BTN, payload=json.dumps({"command": "dating_settings"})),
            color=KeyboardButtonColor.PRIMARY,
        )
        .add(
            Text(MAIN_MENU_BTN, payload=json.dumps({"command": "main"})),
            color=KeyboardButtonColor.SECONDARY,
        )
    )
    return keyboard.get_json()


def build_premium_keyboard() -> str:
    """Под промо премиума: кнопка на страницу оплаты."""
    keyboard = Keyboard(inline=True).add(
        OpenLink(PREMIUM_URL, PREMIUM_BTN),
        color=KeyboardButtonColor.POSITIVE,
    )
    return keyboard.get_json()


def build_rooms_keyboard(selected: str) -> str:
    """Inline-выбор комнаты: выбранная отмечена галочкой."""
    keyboard = Keyboard(inline=True)
    for index, row in enumerate(ROOM_ROWS):
        for key in row:
            label = ROOMS[key]
            if key == selected:
                label = f"{label} ✅"
            keyboard.add(
                Callback(label, payload=json.dumps({"command": "room", "room": key})),
                color=KeyboardButtonColor.SECONDARY,
            )
        if index < len(ROOM_ROWS) - 1:
            keyboard.row()
    return keyboard.get_json()


def build_settings_keyboard(selected: str) -> str:
    """Inline-выбор пола собеседника: выбранный вариант отмечен галочкой."""
    keyboard = Keyboard(inline=True)
    for key in ("female", "male"):
        label = GENDERS[key] + (" ✅" if key == selected else "")
        keyboard.add(
            Callback(label, payload=json.dumps({"command": "gender", "value": key})),
            color=KeyboardButtonColor.PRIMARY,
        )
    keyboard.row()
    label = GENDERS["any"] + (" ✅" if selected == "any" else "")
    keyboard.add(
        Callback(label, payload=json.dumps({"command": "gender", "value": "any"})),
        color=KeyboardButtonColor.SECONDARY,
    )
    return keyboard.get_json()


def build_chat_keyboard() -> str:
    """Под текстом «комната найдена»: «Новый собеседник», «Купить премиум» и «Остановить диалог»."""
    keyboard = (
        Keyboard(inline=True)
        .add(
            Callback(NEW_PARTNER_BTN, payload=json.dumps({"command": "start"})),
            color=KeyboardButtonColor.PRIMARY,
        )
        .row()
        .add(
            OpenLink(PREMIUM_URL, PREMIUM_BTN),
            color=KeyboardButtonColor.POSITIVE,
        )
        .row()
        .add(
            Callback(STOP_BTN, payload=json.dumps({"command": "stop"})),
            color=KeyboardButtonColor.SECONDARY,
        )
    )
    return keyboard.get_json()


def build_partner_left_keyboard() -> str:
    """Под текстом об уходе: синяя «Новый собеседник» и серая «Пожаловаться»."""
    keyboard = (
        Keyboard(inline=True)
        .add(
            Callback(NEW_PARTNER_BTN, payload=json.dumps({"command": "start"})),
            color=KeyboardButtonColor.PRIMARY,
        )
        .row()
        .add(
            Callback(REPORT_BTN, payload=json.dumps({"command": "report"})),
            color=KeyboardButtonColor.SECONDARY,
        )
    )
    return keyboard.get_json()
