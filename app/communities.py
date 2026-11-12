"""Сообщества ВК: набор берётся из CRM (Chat API) и из токенов в env, бот сам запускает и останавливает Long Poll."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from vkbottle import GroupEventType, VKAPIError
from vkbottle.bot import Bot, MessageEvent
from vkbottle.http.aiohttp import AiohttpClient

from app.api_client import ChatApiError, chat_api
from app.config import COMMUNITIES_SYNC_SECONDS
from app.gateway import gateway
from app.handlers import answer_waiting, attach_start_buttons, vk_handler, vk_start_handler
from app.longpoll import VersionedBotPolling
from app.startup import PreflightError, preflight_check

_STATUS_BATCH = 200
_ERROR_LIMIT = 500
_STOP_TIMEOUT = 10.0
_TOKEN_RE = re.compile(r"vk[12]\.[A-Za-z0-9_.\-]+|access_token=[^&\s'\"]+")

# Служебные статусы для CRM (не тексты бота для людей в ВК).
_KEY_FAILED = "Ключ не подошёл: {msg} (код {code})"
_LONGPOLL_FAILED = "Нет доступа к Long Poll: {msg} (код {code})"
_VK_FAILED = "{msg} (код {code})"
_STOPPED_CODE = "Long Poll остановился: {msg} (код {code})"
_STOPPED_MSG = "Long Poll остановился: {msg}"
_STOPPED = "Long Poll остановился"
_NOT_STARTED = "Ещё не запущено"


def clean(message: str, token: str | None = None) -> str:
    """Текст для логов и CRM: без токенов, одной строкой, не длиннее лимита."""
    if token:
        message = message.replace(token, "***")
    message = _TOKEN_RE.sub("***", message)
    return " ".join(message.split())[:_ERROR_LIMIT]


def _fit(template: str, message: str, token: str | None, code: object = "") -> str:
    """Подставляет сообщение ВК в шаблон так, чтобы весь текст влез в лимит, а шаблон не обрывался."""
    message = clean(message, token)
    room = _ERROR_LIMIT - len(template.format(msg="", code=code))
    if len(message) > room:
        message = message[: max(room - 1, 0)].rstrip() + "…"
    return template.format(msg=message, code=code)


def human_error(exc: BaseException, token: str | None = None, *, stopped: bool = False) -> str:
    """Короткое объяснение сбоя для CRM: сообщение ВК и код, без инструкций и токена."""
    if isinstance(exc, PreflightError):
        template = _KEY_FAILED if exc.kind == "key" else _LONGPOLL_FAILED
        return _fit(template, exc.vk_message or "VK", token, exc.code)
    if isinstance(exc, VKAPIError):
        code = getattr(exc, "code", "")
        return _fit(_STOPPED_CODE if stopped else _VK_FAILED, exc.error_msg, token, code)
    text = str(exc) or type(exc).__name__
    if stopped:
        return _fit(_STOPPED_MSG, f"{type(exc).__name__}: {text}", token)
    return clean(text, token)


class CheckFailed(RuntimeError):
    """Проверка токена не прошла. crm — текст для CRM, str() — полный текст для логов."""

    def __init__(self, log: str, crm: str) -> None:
        super().__init__(log)
        self.crm = crm


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


def attach_handlers(bot: Bot, bot_key: str) -> None:
    """Подключает обработчики сообщений и inline-кнопок к боту сообщества."""
    bot.on.message()(vk_handler(bot_key))
    bot.on.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent)(vk_start_handler(bot_key))


def log_task_end(task: asyncio.Task, token: str | None = None) -> None:
    """Печатает падение задачи. Иначе vkbottle пишет ошибку только в loguru."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        detail = clean(f"{type(exc).__name__}: {exc}", token)
        print(f"Задача {task.get_name()} упала: {detail}", flush=True)


async def listen(bot: Bot, group_id: str) -> None:
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


@dataclass
class _Running:
    token: str
    bot: Any
    task: asyncio.Task


class CommunityManager:
    """Держит запущенные сообщества и раз в COMMUNITIES_SYNC_SECONDS сверяет их с CRM.

    Желаемый набор = сообщества из Chat API (включённые, с токеном) плюс токены из env,
    чьих group_id нет ни в списке, ни среди отключённых. Недоступный Chat API набор не меняет.
    """

    def __init__(
        self,
        env_tokens: list[str],
        *,
        api: Any = chat_api,
        interval: float = COMMUNITIES_SYNC_SECONDS,
        preflight: Callable[[str], tuple[int, str]] = preflight_check,
        make_bot: Callable[[str], Any] = community_bot,
        attach: Callable[[Any, str], None] = attach_handlers,
        listener: Callable[[Any, str], Awaitable[None]] = listen,
    ) -> None:
        self._env_tokens = list(env_tokens)
        self._api = api
        self._interval = interval
        self._preflight = preflight
        self._make_bot = make_bot
        self._attach = attach
        self._listener = listener
        self._running: dict[str, _Running] = {}
        self._env_info: dict[str, tuple[int, str]] = {}  # токен env -> (group_id, название)
        self._errors: dict[str, str] = {}  # group_id -> текст для CRM
        self._imported: set[str] = set()  # env-токены, принятые CRM без ошибки
        self._api_last: dict | None = None  # последний удачный ответ CRM
        self.ready = asyncio.Event()  # первая синхронизация завершена

    @property
    def running_ids(self) -> list[str]:
        return sorted(self._running)

    _clean = staticmethod(clean)

    async def _check(self, token: str) -> tuple[int, str]:
        """Синхронная проверка доступа к Long Poll выполняется в потоке, чтобы не блокировать цикл."""
        try:
            return await asyncio.to_thread(self._preflight, token)
        except (SystemExit, Exception) as exc:  # noqa: BLE001 — preflight сообщает отказ через SystemExit
            raise CheckFailed(clean(str(exc) or type(exc).__name__, token), human_error(exc, token)) from None

    async def _resolve_env(self) -> None:
        """Проверяет env-токены, которые ещё не удалось проверить, и передаёт их токены в CRM."""
        for token in self._env_tokens:
            if token in self._env_info:
                continue
            try:
                group_id, name = await self._check(token)
            except CheckFailed as exc:
                print(f"Токен сообщества пропущен: {exc}", flush=True)
                continue
            self._env_info[token] = (group_id, name)
        for token, (group_id, name) in list(self._env_info.items()):
            if token in self._imported:
                continue
            try:
                if await self._api.import_vk_community(group_id, name, token):
                    print(f"Токен group_id={group_id} передан в CRM", flush=True)
                self._imported.add(token)  # без ошибки: повторять не нужно
            except ChatApiError as exc:
                print(f"Не передал токен group_id={group_id} в CRM: {clean(str(exc), token)}", flush=True)

    async def _fetch(self) -> dict | None:
        """Список сообществ из CRM. Сбой — прежний список (или None, если его не было)."""
        try:
            self._api_last = await self._api.vk_communities()
        except ChatApiError as exc:
            print(f"Список сообществ из CRM недоступен, набор не меняю: {exc}", flush=True)
        return self._api_last

    def _desired(self, remote: dict | None) -> dict[str, tuple[str, str]]:
        """group_id -> (токен, название) для всех сообществ, которые должны работать."""
        wanted: dict[str, tuple[str, str]] = {}
        known: set[str] = set()
        if remote:
            for item in remote.get("communities") or []:
                group_id, token = str(item.get("group_id")), str(item.get("token") or "")
                known.add(group_id)
                if token:
                    wanted[group_id] = (token, str(item.get("title") or ""))
            known.update(str(value) for value in remote.get("disabled") or [])
        for token, (group_id, name) in self._env_info.items():
            if str(group_id) not in known:
                wanted.setdefault(str(group_id), (token, name))
        return wanted

    async def _start(self, group_id: str, token: str, title: str) -> None:
        """Проверка Long Poll, запись в CRM, бот, обработчики и задача. Ошибка запоминается."""
        info = self._env_info.get(token)
        try:
            resolved_id, name = info if info else await self._check(token)
            if str(resolved_id) != group_id:
                raise RuntimeError(f"Токен принадлежит сообществу {resolved_id}, а не {group_id}")
            try:
                await self._api.register_channel("vk", group_id, name or title)
            except ChatApiError as exc:
                print(f"Не записал сообщество group_id={group_id}: {self._clean(str(exc), token)}", flush=True)
            bot = self._make_bot(token)
            try:
                gateway.add(group_id, bot.api)
                self._attach(bot, group_id)
                task = asyncio.create_task(self._listener(bot, group_id), name=f"vk-{group_id}")
            except BaseException:
                gateway.remove(group_id)
                await self._close_bot(bot)
                raise
        except Exception as exc:  # noqa: BLE001 — одно сообщество не должно ронять остальные
            self._errors[group_id] = exc.crm if isinstance(exc, CheckFailed) else human_error(exc, token)
            detail = clean(str(exc) or type(exc).__name__, token)
            print(f"Сообщество group_id={group_id} не запущено: {detail}", flush=True)
            return
        task.add_done_callback(partial(log_task_end, token=token))
        self._running[group_id] = _Running(token, bot, task)
        self._errors.pop(group_id, None)
        print(f"VK: сообщество на Long Poll (group_id={group_id})", flush=True)

    @staticmethod
    async def _close_bot(bot: Any) -> None:
        try:
            await bot.api.http_client.close()
        except Exception as exc:  # noqa: BLE001
            print(f"Не закрыл HTTP-клиент сообщества: {type(exc).__name__}", flush=True)

    async def _stop(self, group_id: str) -> None:
        """Останавливает Long Poll, задачу и сессию сообщества. Не бросает исключений."""
        running = self._running.pop(group_id, None)
        if running is None:
            return
        gateway.remove(group_id)  # сразу: новые доставки в это сообщество не пойдут
        try:
            running.bot.polling.stop()
        except Exception:  # noqa: BLE001 — до первого listen() события остановки ещё нет
            pass
        running.task.cancel()
        try:
            await asyncio.wait_for(asyncio.gather(running.task, return_exceptions=True), _STOP_TIMEOUT)
        except asyncio.TimeoutError:
            print(f"Задача group_id={group_id} не остановилась за {_STOP_TIMEOUT:.0f} с", flush=True)
        await self._close_bot(running.bot)
        print(f"VK: сообщество остановлено (group_id={group_id})", flush=True)

    async def _reconcile(self, wanted: dict[str, tuple[str, str]]) -> None:
        for group_id in [key for key in self._running if key not in wanted]:
            await self._stop(group_id)
        for group_id in [key for key in self._errors if key not in wanted]:
            del self._errors[group_id]
        for group_id, (token, title) in wanted.items():
            current = self._running.get(group_id)
            if current is None:
                pass
            elif current.token != token:
                print(f"Токен group_id={group_id} заменён в CRM, перезапускаю", flush=True)
                await self._stop(group_id)
            elif current.task.done():
                exc = None if current.task.cancelled() else current.task.exception()
                self._errors[group_id] = human_error(exc, token, stopped=True) if exc else _STOPPED
                await self._stop(group_id)
            else:
                continue
            await self._start(group_id, token, title)

    async def _report(self, wanted: dict[str, tuple[str, str]]) -> None:
        items: list[dict] = []
        for group_id in wanted:
            try:
                numeric = int(group_id)
            except ValueError:
                continue
            running = self._running.get(group_id)
            if running is not None and not running.task.done():
                items.append({"group_id": numeric, "status": "ok", "error": ""})
            else:
                items.append(
                    {"group_id": numeric, "status": "error", "error": self._errors.get(group_id, _NOT_STARTED)}
                )
        for index in range(0, len(items), _STATUS_BATCH):
            try:
                await self._api.report_vk_status(items[index : index + _STATUS_BATCH])
            except ChatApiError as exc:
                print(f"Не отправил статусы сообществ: {exc}", flush=True)
                return

    async def sync(self) -> None:
        """Один тик: токены env, список из CRM, запуск/остановка, статусы."""
        await self._resolve_env()
        wanted = self._desired(await self._fetch())
        await self._reconcile(wanted)
        await self._report(wanted)

    async def stop_all(self) -> None:
        for group_id in list(self._running):
            await self._stop(group_id)

    async def run(self) -> None:
        """Работает до отмены. Сбой тика не завершает процесс."""
        try:
            try:
                await self.sync()
            except Exception as exc:  # noqa: BLE001 — первый тик не должен завершать процесс
                print(f"Сбой синхронизации сообществ: {clean(f'{type(exc).__name__}: {exc}')}", flush=True)
            self.ready.set()
            if not self._running:
                print("Ни одно сообщество пока не запущено, жду CRM и env.", flush=True)
            while True:
                await asyncio.sleep(self._interval)
                try:
                    await self.sync()
                except Exception as exc:  # noqa: BLE001
                    print(f"Сбой синхронизации сообществ: {clean(f'{type(exc).__name__}: {exc}')}", flush=True)
        finally:
            await asyncio.shield(self.stop_all())
