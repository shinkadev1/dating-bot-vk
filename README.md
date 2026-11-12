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

Клавиатуру и ответы бота можно крутить без Chat API. `DEV_MODE=True` подменяет вызовы
заглушкой в памяти и не читает события. `DEV_MODE=False` — обычный Chat API. Деплой флаг не копирует.

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Тот же режим без Compose: `DEV_MODE=True` в `.env` и `python -m app.main`.
Сообщества ВК бот берёт из двух источников: из CRM (Chat API, `GET /channels/vk/tokens`) и из токенов `VK_TOKEN`/`VK_TOKENS`.
Токены из env бот при старте передаёт в CRM (`POST /channels/vk/import`, существующие не перезаписываются). Раз в `COMMUNITIES_SYNC_SECONDS` (по умолчанию 60) он сверяется с CRM: запускает новые сообщества, останавливает отключённые, перезапускает при замене токена и отправляет статус (`POST /channels/vk/status`). Токен из env, чьего сообщества нет в CRM и среди отключённых, продолжает работать. Если Chat API недоступен или старый (404/503), бот работает на env-токенах. Без токенов в env бот не падает и ждёт сообщества из CRM.

Long Poll ВК один на токен сообщества. Пока прод-контейнер слушает основное сообщество,
в локальный запуск нужен другой токен, иначе события уйдут локальному процессу.

## Тексты и кнопки: flow/flow.yaml

Все тексты, кнопки, клавиатуры, цвета, картинки (`flow/images/`), переходы и тосты лежат в `flow/flow.yaml`,
структура описана в `flow/flow.schema.json` (version 1, схема общая с ботом Telegram). Файл читает и правит CRM «Постдеск».

- Экран = узел карты (`title` и `pos` обязательны), кнопка `goto`/`next` = ребро. Кнопка с `action` вызывает код,
  с `goto` показывает другой экран без правок кода, с `url` открывает ссылку (только inline-экраны).
- `keyboard: reply` — нижняя клавиатура, `inline` — кнопки под сообщением. Цвет кнопки — `style`
  (primary — синий, secondary — серый, success — зелёный, danger — красный), задаётся всегда.
- Подпись кнопки до 40 символов, payload до 255. Нижние кнопки работают по payload `{"command": "<action>"}`,
  текстом работают только start, report, stop и next (подпись кнопки или `aliases`).
- Новое `action`, `handler` или `on` сначала добавляется в код (`ACTIONS`/`HANDLERS` в `app/handlers.py`, `EVENTS` в `app/events.py`),
  затем во flow. Ломающие изменения формата — только с повышением `version`.
- Проверка: `python -m app.flow` (выводит «flow загружен: N экранов, M текстов», при ошибке — код 1 и путь до поля)
  и `python -m unittest discover -s tests -v`. Бот с битым flow не стартует; CI запускает обе проверки до сборки образа.

## Прод

Push в `master` собирает образ `dating-bot` и перезапускает контейнер на сервере бота.

Секреты GitHub:

- `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`
- `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` — SSH на сервер бота
- `DEPLOY_PATH` — каталог бота, по умолчанию `~/dating-bot-vk`
- `ENV_FILE` — `VK_TOKEN` (необязателен: без него деплой только предупреждает), `CHAT_API_SERVICE_TOKEN`, `CHAT_API_URL`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`
