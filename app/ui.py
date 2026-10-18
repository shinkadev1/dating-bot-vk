"""Тексты, подписи кнопок и клавиатуры сообщений."""

import json
import random

from vkbottle import Callback, Keyboard, KeyboardButtonColor

MENU_TEXT = "Найди собеседника прямо сейчас"
COMMUNITY_GREETING = (
    "👋 Привет! Это чат для анонимных знакомств, флирта и легкого общения\n"
    "Найди собеседника прямо сейчас. Нажми кнопку начать"
)
START_BTN = "Начать"

CHAT_BTN_NEXT = "➡️ Следующий собеседник"
CHAT_BTN_STOP = "🛑 Закончить диалог"
NEW_PARTNER_BTN = "🔍 Новый собеседник"
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


def empty_keyboard() -> str:
    """Снимает нижнюю клавиатуру над полем ввода."""
    return Keyboard().get_empty_keyboard()


def build_chat_keyboard() -> str:
    """Под текстом «комната найдена»: синяя «Новый собеседник» и серая «Остановить диалог»."""
    keyboard = (
        Keyboard(inline=True)
        .add(
            Callback(NEW_PARTNER_BTN, payload=json.dumps({"command": "start"})),
            color=KeyboardButtonColor.PRIMARY,
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
