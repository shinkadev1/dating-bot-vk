# Бот ВК

Принимает сообщения сообщества ВК и передаёт их в Chat API (репозиторий `dating-bot`).
Очередь и пары живут в Chat API. Бот вызывает REST и читает события из Redis Streams.

На сервере контейнер `vk-bot` подключается к сети Compose Chat API и видит `chat-api` и `redis`.

## Локальный запуск

Сначала поднимите Chat API: он создаёт сеть `vk-bot_default`.
`CHAT_API_SERVICE_TOKEN` в `.env` должен совпадать с токеном Chat API.

```sh
cp .env.example .env
docker compose up --build
```

## Прод

Push в `master` собирает образ `dating-bot` и перезапускает контейнер на сервере Chat API.

Секреты GitHub:

- `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`
- `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` — SSH на сервер Chat API
- `DEPLOY_PATH` — каталог бота, по умолчанию `~/dating-bot-vk`
- `CHAT_APP_DIR` — каталог Chat API, по умолчанию `~/dating-bot`. Оттуда читается `CHAT_API_SERVICE_TOKEN`
- `ENV_FILE` — токены сообществ ВК
