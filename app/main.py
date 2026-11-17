"""Запуск бота ВК: на каждое сообщество свой Bot и своя задача Long Poll."""

import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from app import flow
from app.api_client import chat_api
from app.communities import CommunityManager, log_task_end
from app.config import CHAT_API_SERVICE_TOKEN, CHAT_API_URL, DEV_MODE, vk_tokens
from app.events import EVENTS, consume_broadcasts, consume_events
from app.handlers import ACTIONS, HANDLERS
from app.startup import rebuild_vkbottle_response_models

# Карта читается и сверяется с кодом до запуска Long Poll: битый flow.yaml или расхождение
# с реестрами ACTIONS/HANDLERS/EVENTS — FlowError, бот не стартует.
_FLOW = flow.get()
_FLOW.check_registries(actions=ACTIONS, handlers=HANDLERS, events=EVENTS)
print(f"flow загружен: {len(_FLOW.screens)} экранов, {len(_FLOW.texts)} текстов", flush=True)


async def _run() -> None:
    """Запускает менеджер сообществ и потребителей событий Chat API."""
    if not DEV_MODE and not CHAT_API_SERVICE_TOKEN:
        raise SystemExit("Не задан CHAT_API_SERVICE_TOKEN: без него Chat API не примет запросы бота.")

    rebuild_vkbottle_response_models()
    tokens = vk_tokens()
    print(f"Токенов ВК в env: {len(tokens)}.", flush=True)
    if not tokens:
        print("Токены ВК в env не заданы: сообщества берутся из CRM.", flush=True)
    manager = CommunityManager(tokens)
    # Потребители событий стартуют после первой синхронизации: к этому времени
    # сообщества уже в gateway и есть кому доставлять.
    runner = asyncio.create_task(manager.run(), name="communities")
    ready = asyncio.create_task(manager.ready.wait())
    await asyncio.wait({runner, ready}, return_when=asyncio.FIRST_COMPLETED)
    ready.cancel()

    listeners: list[asyncio.Task] = []
    if DEV_MODE:
        print("Dev-режим: Chat API замокан, события не читаю.", flush=True)
    else:
        events = asyncio.create_task(consume_events(), name="chat-events")
        events.add_done_callback(log_task_end)
        broadcasts = asyncio.create_task(consume_broadcasts(), name="chat-broadcasts")
        broadcasts.add_done_callback(log_task_end)
        listeners.extend((events, broadcasts))
        print(f"Логика чата: Chat API {CHAT_API_URL}.")
    print("Бот запущен. Ожидаю сообщения...", flush=True)
    try:
        await runner
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
        for listener in listeners:
            listener.cancel()
        if listeners:
            await asyncio.gather(*listeners, return_exceptions=True)
        await chat_api.aclose()


def main() -> None:
    """Запускает бота и печатает причину падения."""
    try:
        asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка запуска: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
