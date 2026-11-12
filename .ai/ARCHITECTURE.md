# Архитектура dating-bot-vk

Проверено: **2026-10-31**.

## Поток данных

VK Long Poll → handlers → REST Chat API. Обратная доставка: `/api/v1/events/vk` и `/api/v1/broadcasts/vk` → events → gateway → VK. Worker заявок независим от поиска и диалогов.

## Точки входа

| Путь | Ответственность |
| --- | --- |
| `app/main.py` | Запуск ботов сообществ и обработчиков событий. |
| `app/longpoll.py` | Входящие события VK. |
| `app/startup.py` | Подготовка сообществ и обработка ожидающих сообщений. |
| `app/handlers.py` | Маршрутизация по `flow.action_for` и payload, реестры `ACTIONS`/`HANDLERS`, переходы goto, фазы UI, города, пол и возраст. |
| `app/flow.py` | Загрузка и проверка `flow/flow.yaml` по `flow/flow.schema.json`, сверка с реестрами кода; `python -m app.flow`. |
| `app/ui.py` | Сборка клавиатур vkbottle из flow; прежние публичные имена (`MENU_TEXT`, `FIND_BTN`, `ROOMS` …). |
| `app/gateway.py` | Доставка текста, баннеров и медиа. |
| `app/api_client.py` | REST Chat API. |
| `app/premium.py` | Личная ссылка оплаты премиума и его срок, кэш на пользователя. |
| `app/events.py` | WebSocket событий и рассылок с ack; реестр `EVENTS`. Событие `partner_left` с флагом `promo: true` (каждый 10-й завершённый диалог, из Chat API; не выкачено) без активного премиума → экран `partner_left_promo` вместо обычного; `undeliverable` флаг игнорирует. Отдельного события promo нет. Аналогично `POST /stop` с `promo: true` → экран `stopped_promo` (см. `stop_active` в `app/handlers.py`, `StopResult` в `app/api_client.py`). |
| `app/media.py` | Обработка файлов. |
| `app/mock_api.py` | Заглушка Chat API. |
| `worker/src/` | Callback API Worker для заявок в сообщество. |

## Контракты и ограничения

- Бот не подключается к Redis напрямую. Redis остаётся у Chat API; WebSocket-события подтверждаются через ack.
- Compose подключается к внешней сети `CHAT_NETWORK`.
- Комнаты, пол и возраст хранятся в памяти обработчиков и не передаются в серверный поиск.
- Уведомления notice не должны закрывать пару или подменять клавиатуру диалога.
- Кнопки премиума ведут на личную ссылку из `GET /api/v1/peers/vk/{bot_key}/{user_id}/premium/link` (ветка `payments` vk-bot). Ссылка живёт 24 часа и уходит только кнопкой OpenLink, не текстом: ВК открыл бы её для сниппета. Клавиатура диалога берёт ссылку из кэша на час, промо и отказ в медиа — свежую. Ошибка или 503 — статичная `PREMIUM_URL`; при активном премиуме вместо продажи срок «до ДД.ММ.ГГГГ» (МСК).

## Flow

`flow/flow.yaml` описывает экраны (`title`, `pos`, `text`, `image`, `keyboard`, `buttons`, `next`, `handler`, `on`, `options`), служебные `texts` и тосты; `flow/images/` — картинки. Схема `flow/flow.schema.json` (version 1) общая с ботом Telegram и читается CRM «Постдеск». Код регистрирует `ACTIONS`, `HANDLERS`, `EVENTS`; их равенство набору во flow проверяют тесты, `python -m app.flow` и старт бота (`app/main.py`). Бот не стартует с битым flow (`FlowError`).

## Развёртывание

Push в `master` запускает `.github/workflows/deploy.yml`: job `validate` (`python -m app.flow`, unittest) → `publish` → `deploy`; обновление — `deploy/update.sh` (после старта проверяет `running` и `RestartCount` контейнера `vk-bot`). Образ копирует `flow/` в `/app/flow`. Worker деплоится отдельно.

Схема описывает репозиторий, а не подтверждённое состояние production.
