"""Настройки запуска: токены сообществ, версия API ВК и адреса Chat API."""

import os

API_VERSION = "5.199"


def vk_tokens() -> list[str]:
    """Токены сообществ ВК из VK_TOKEN и VK_TOKENS через запятую. Повторы отбрасывает."""
    found: list[str] = []
    for name in ("VK_TOKEN", "VK_TOKENS"):
        for part in (os.getenv(name) or "").replace(";", ",").split(","):
            token = part.strip()
            if token and token not in found:
                found.append(token)
    return found


# Логика чата живёт в Chat API. Бот вызывает его REST и читает события из Redis.
CHAT_API_URL = (os.getenv("CHAT_API_URL") or "http://localhost:8000").strip()
CHAT_API_SERVICE_TOKEN = (os.getenv("CHAT_API_SERVICE_TOKEN") or "").strip()
REDIS_URL = (os.getenv("REDIS_URL") or "redis://localhost:6379/0").strip()
# Имя потребителя в группе Redis. Постоянное, чтобы после перезапуска дочитать неподтверждённые события.
EVENTS_CONSUMER = (os.getenv("EVENTS_CONSUMER") or "bot").strip()
