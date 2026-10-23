"""Запуск бота ВК: на каждое сообщество свой Bot и своя задача Long Poll."""

import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from vkbottle import GroupEventType
from vkbottle.bot import Bot, MessageEvent
from vkbottle.http.aiohttp import AiohttpClient

from app.api_client import ChatApiError, chat_api
from app.config import CHAT_API_SERVICE_TOKEN, CHAT_API_URL, DEV_MODE, vk_tokens
from app.events import consume_broadcasts, consume_events
from app.gateway import gateway
from app.handlers import answer_waiting, attach_start_buttons, vk_handler, vk_start_handler
from app.longpoll import VersionedBotPolling
from app.startup import preflight_check, rebuild_vkbottle_response_models


def community_bot(token: str) -> Bot:
    """Отдельный Bot на один токен и свой HTTP-клиент.

    Общий клиент vkbottle рвёт соединения соседних сообществ. Без version Long Poll не отдаёт события.
    """
    bot = Bot(token)
    bot.api.http_client = AiohttpClient()
    bot._polling = VersionedBotPolling(  # noqa: SLF001 — других способов подменить polling нет
        bot.api,
        error_handler=bot.error_handler,
        skip_old_events=bot.skip_old_events,
    )
    return bot


def _log_task_end(task: asyncio.Task) -> None:
    """Печатает падение задачи. Иначе vkbottle пишет ошибку только в loguru."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        print(f"Задача {task.get_name()} упала: {type(exc).__name__}: {exc}", flush=True)


async def _listen(bot: Bot, group_id: str) -> None:
    """Одна задача: сначала отвечает ожидающим сообщениям, потом слушает Long Poll."""
    print(f"Слушаю сообщество group_id={group_id}", flush=True)
    try:
        await answer_waiting(bot.api, group_id)
        await attach_start_buttons(bot.api, group_id)
    except Exception as exc:  # noqa: BLE001 — сбой разбора старых сообщений не должен останавливать бота
        print(
            f"Не ответил на ожидающие group_id={group_id}: {type(exc).__name__}: {exc}",
            flush=True,
        )
    await bot.run_polling()


async def _run() -> None:
    """Проверяет токены и запускает отдельную задачу на каждое сообщество."""
    tokens = vk_tokens()
    if not tokens:
        raise SystemExit("Не задан токен сообщества. Укажите VK_TOKEN или VK_TOKENS.")
    if not DEV_MODE and not CHAT_API_SERVICE_TOKEN:
        raise SystemExit("Не задан CHAT_API_SERVICE_TOKEN: без него Chat API не примет запросы бота.")

    rebuild_vkbottle_response_models()
    tasks: list[asyncio.Task] = []
    print(f"Токенов ВК: {len(tokens)}.")
    for token in tokens:
        try:
            group_id, group_name = preflight_check(token)
        except SystemExit as exc:
            print(f"Токен сообщества пропущен: {exc}", file=sys.stderr)
            continue
        bot_key = str(group_id)
        try:
            await chat_api.register_channel("vk", bot_key, group_name)
        except ChatApiError as exc:
            print(f"Не записал сообщество group_id={group_id}: {exc}", flush=True)
        bot = community_bot(token)
        gateway.add(bot_key, bot.api)
        bot.on.message()(vk_handler(bot_key))
        bot.on.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent)(vk_start_handler(bot_key))
        task = asyncio.create_task(_listen(bot, bot_key), name=f"vk-{bot_key}")
        task.add_done_callback(_log_task_end)
        tasks.append(task)
        print(f"VK: сообщество на Long Poll (group_id={group_id})")
    if not tasks:
        raise SystemExit("Ни одно сообщество не прошло проверку Long Poll.")

    listeners: list[asyncio.Task] = []
    if DEV_MODE:
        print("Dev-режим: Chat API замокан, события не читаю.", flush=True)
    else:
        events = asyncio.create_task(consume_events(), name="chat-events")
        events.add_done_callback(_log_task_end)
        broadcasts = asyncio.create_task(consume_broadcasts(), name="chat-broadcasts")
        broadcasts.add_done_callback(_log_task_end)
        listeners.extend((events, broadcasts))
        print(f"Логика чата: Chat API {CHAT_API_URL}.")
    print("Бот запущен. Ожидаю сообщения...")
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        for listener in listeners:
            listener.cancel()
        if listeners:
            await asyncio.gather(*listeners, return_exceptions=True)
        await chat_api.aclose()
    errors = [result for result in results if isinstance(result, BaseException)]
    if errors and len(errors) == len(results):
        raise errors[0]


def main() -> None:
    """Запускает бота и печатает причину падения."""
    try:
        asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка запуска: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
