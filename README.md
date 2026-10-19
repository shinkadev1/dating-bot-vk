# Бот ВК

Принимает сообщения сообщества ВК и передаёт их в Dating API (репозиторий `dating-api`).
Очередь и пары живут в Chat API. Redis тоже остаётся там. Бот запускается своим Compose
и получает события по WebSocket `/api/v1/events/vk` и `/api/v1/broadcasts/vk`.

## Локальный запуск

`CHAT_API_SERVICE_TOKEN` в `.env` должен совпадать с токеном Chat API.
Для публичного адреса нужны `CF_ACCESS_CLIENT_ID` и `CF_ACCESS_CLIENT_SECRET`.

```sh
cp .env.example .env
docker compose up --build
```

## Прод

Push в `master` собирает образ `dating-bot` и перезапускает контейнер на сервере бота.

Секреты GitHub:

- `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`
- `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` — SSH на сервер бота
- `DEPLOY_PATH` — каталог бота, по умолчанию `~/dating-bot-vk`
- `ENV_FILE` — `VK_TOKEN`, `CHAT_API_SERVICE_TOKEN`, `CHAT_API_URL`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`
