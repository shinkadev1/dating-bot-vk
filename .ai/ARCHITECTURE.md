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
| `app/handlers.py` | Команды, фазы UI, комнаты, пол и возраст. |
| `app/ui.py` | Тексты и клавиатуры. |
| `app/gateway.py` | Доставка текста, баннеров и медиа. |
| `app/api_client.py` | REST Chat API. |
| `app/events.py` | WebSocket событий и рассылок с ack. |
| `app/media.py` | Обработка файлов. |
| `app/mock_api.py` | Заглушка Chat API. |
| `worker/src/` | Callback API Worker для заявок в сообщество. |

## Контракты и ограничения

- Бот не подключается к Redis напрямую. Redis остаётся у Chat API; WebSocket-события подтверждаются через ack.
- Compose подключается к внешней сети `CHAT_NETWORK`.
- Комнаты, пол и возраст хранятся в памяти обработчиков и не передаются в серверный поиск.
- Уведомления notice не должны закрывать пару или подменять клавиатуру диалога.

## Развёртывание

Push в `master` запускает `.github/workflows/deploy.yml`; обновление — `deploy/update.sh`. Worker деплоится отдельно.

Схема описывает репозиторий, а не подтверждённое состояние production.
