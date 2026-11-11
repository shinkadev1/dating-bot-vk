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
Long Poll ВК один на токен сообщества. Пока прод-контейнер слушает основное сообщество,
в локальный запуск нужен другой токен, иначе события уйдут локальному процессу.

## Прод

Push в `master` собирает образ `dating-bot` и перезапускает контейнер на сервере бота.

Секреты GitHub:

- `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`
- `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` — SSH на сервер бота
- `DEPLOY_PATH` — каталог бота, по умолчанию `~/dating-bot-vk`
- `ENV_FILE` — `VK_TOKEN`, `CHAT_API_SERVICE_TOKEN`, `CHAT_API_URL`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`

## Тексты, кнопки и картинки

Всё, что видит пользователь, лежит отдельно от кода в `app/content/`:

- `content.json` — тексты сообщений (`texts`), подписи кнопок (`buttons`) и их прежние подписи
  (`button_aliases`), списки городов, пола и тарифов (`lists`), раскладка и цвета клавиатур (`keyboards`),
  картинки (`images`) и описание экранов для превью (`screens`);
- `images/` — баннеры.

Файл редактируется в Bot CRM; код читает его при запуске (`app/content.py`), поэтому после правки
бота нужно перезапустить. Команды кнопок (payload) остаются в коде (`app/ui.py: _BUTTON_COMMANDS`),
поэтому переименование кнопки ничего не ломает. ВК не принимает подписи длиннее 40 символов —
это проверяет `tests/test_content.py` вместе с целостностью ссылок.
