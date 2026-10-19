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


# Логика чата живёт в Chat API. Бот вызывает его REST и получает события по WebSocket.
# Redis остаётся внутри Chat API: бот к нему не подключается и может работать на другом сервере.
CHAT_API_URL = (os.getenv("CHAT_API_URL") or "https://api.chatwithyou.site").strip().rstrip("/")
CHAT_API_SERVICE_TOKEN = (os.getenv("CHAT_API_SERVICE_TOKEN") or "").strip()
# Сервисный токен Cloudflare Access перед api.chatwithyou.site. Для адреса внутри сети не нужен.
CF_ACCESS_CLIENT_ID = (os.getenv("CF_ACCESS_CLIENT_ID") or "").strip()
CF_ACCESS_CLIENT_SECRET = (os.getenv("CF_ACCESS_CLIENT_SECRET") or "").strip()
# Имя потребителя в группе Redis. Постоянное, чтобы после перезапуска дочитать неподтверждённые события.
EVENTS_CONSUMER = (os.getenv("EVENTS_CONSUMER") or "bot").strip()


def chat_api_headers(token: str | None = None) -> dict[str, str]:
    """Заголовки каждого запроса к Chat API: токен бота и, если задан, токен Cloudflare Access."""
    headers = {"Authorization": f"Bearer {token if token is not None else CHAT_API_SERVICE_TOKEN}"}
    if CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET:
        headers["CF-Access-Client-Id"] = CF_ACCESS_CLIENT_ID
        headers["CF-Access-Client-Secret"] = CF_ACCESS_CLIENT_SECRET
    return headers
