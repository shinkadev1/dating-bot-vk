"""Long Poll сообщества с обязательным параметром version.

Без version VK отвечает failed=4 и не отдаёт message_new. Эта ошибка пишется
в loguru и в логах контейнера её не видно, поэтому первые сбои печатаем здесь.
"""

from aiohttp import ClientTimeout
from vkbottle.polling.bot_polling import BotPolling


class VersionedBotPolling(BotPolling):
    """Тот же BotPolling, но a_check всегда передаёт версию протокола."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._fail_logs = 0
        self._saw_updates = False

    async def get_event(self, server: dict) -> dict:
        version = self.lp_version or 3
        event = await self.api.http_client.request_json(
            url=server["server"],
            method="POST",
            params={
                "act": "a_check",
                "key": server["key"],
                "ts": server["ts"],
                "wait": self.wait,
                "version": version,
            },
            timeout=ClientTimeout(total=self.wait + 10),
        )
        failed = event.get("failed")
        if failed is not None and self._fail_logs < 5:
            self._fail_logs += 1
            print(
                f"Long Poll group_id={self.group_id} failed={failed} "
                f"min={event.get('min_version')} max={event.get('max_version')}",
                flush=True,
            )
            if failed == 4 and event.get("max_version"):
                self.lp_version = int(event["max_version"])
        updates = event.get("updates") or []
        if updates and not self._saw_updates:
            self._saw_updates = True
            print(
                f"Long Poll group_id={self.group_id} получил {len(updates)} событий",
                flush=True,
            )
        return event
