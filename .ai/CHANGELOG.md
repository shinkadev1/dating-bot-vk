# История важных изменений

## 2026-11-12 — сообщества ВК из CRM (ветка loop/vk-communities-crm, не выкачено)

Контракт Chat API: `GET /channels/vk/tokens` -> `{communities:[{group_id,title,token}], disabled:[group_id]}`, `POST /channels/vk/import {group_id,title,token}` -> `{stored}`, `POST /channels/vk/status {items:[{group_id,status,error}]}` -> 204. `CommunityManager` держит желаемый набор = сообщества CRM ∪ env-токены, которых нет в CRM и среди отключённых; раз в `COMMUNITIES_SYNC_SECONDS` (60) запускает новые, останавливает отключённые (polling.stop, cancel, gateway.remove, закрытие HTTP-клиента), перезапускает при смене токена, повторяет упавший preflight (в потоке) и шлёт статусы. 404/503/сбой сети — работа на env-токенах. Бот не выходит без токенов; `deploy/update.sh` без VK_TOKEN предупреждает, а не падает. Пользовательские тексты и flow не менялись. Тесты: `tests/test_communities.py`.

## 2026-11-12 — размытое фото без премиума (ветка loop/photo-blur, не выкачено)

Контракт Chat API: событие `media` может содержать `locked: true` — тогда `media_id` указывает на размытую копию фото (image/jpeg). `events._deliver` скачивает байты и вызывает `gateway.send_locked_photo`: фото вложением, текст «🔒 Просмотр фото доступен только с премиумом» и inline-кнопка «💎 Купить премиум» с личной ссылкой (экран `photo_locked` в `flow/flow.yaml` без `on`, `PHOTO_LOCKED_TEXT` в `app/ui.py`). Схема и version flow не менялись. Тесты: `tests/test_photo_locked.py`. Живой VK не проверен.

## 2026-11-12 — промо премиума каждые 10 диалогов (ветка loop/promo-every-10, не выкачено)

Контракт Chat API: событие `partner_left` может содержать `promo: true`, ответ `POST /stop` — `promo: true` (по умолчанию false); отдельного события promo нет. `api_client.stop()` возвращает `StopResult(was_active, promo)`. Без активного премиума бот показывает экраны `partner_left_promo` и `stopped_promo` (`flow/flow.yaml`, `images/premium.png`, кнопки «Купить премиум» с личной ссылкой, «Новый собеседник», в первом ещё «Пожаловаться»); при премиуме и без флага поведение прежнее. Экран `premium_promo` удалён. Тесты: `tests/test_promo_event.py`. Зависит от vk-bot (не выкачено, выкатывается после ботов; живой VK не проверен).

## 2026-11-11 — flow/flow.yaml

Пользовательские тексты, кнопки, клавиатуры, цвета, картинки, переходы и тосты бота переехали в `flow/flow.yaml` (+ `flow/flow.schema.json`, `flow/images`): CRM «Постдеск» читает и правит файл в GitHub и рисует карту бота. Поведение для пользователя не менялось: эквивалентность подтверждена снимком кода до перехода (`tests/fixtures/ui_snapshot.json`). Единственное отличие: нажатия inline-кнопок с действиями `dating_rooms`, `dating_settings`, `next`, которые раньше молча игнорировались (таких кнопок нет), теперь выполняются по имени action. Новое: `app/flow.py` (загрузка, схема, лимиты ВК, сверка с реестрами `ACTIONS`/`HANDLERS`/`EVENTS` при старте, проверка полей шаблонов), общий рендер экранов goto/next без кода, тест «нет пользовательских литералов в коде», job `validate` в CI, проверка `RestartCount` в `deploy/update.sh`. Файлы: `app/flow.py`, `app/ui.py`, `app/handlers.py`, `app/gateway.py`, `app/events.py`, `app/main.py`, `flow/`, `tests/`, `Dockerfile`, `requirements.txt`, `.github/workflows/deploy.yml`, `deploy/update.sh`. Проверки: `python -m app.flow`, `python -m unittest discover -s tests -v`. Не проверено: docker build, деплой, живой VK.

## 2026-11-03 — личная ссылка оплаты премиума (ветка paylink)

Кнопки «Купить премиум» в промо, воротах «Чата знакомств», клавиатуре диалога и отказе в медиа открывают личную ссылку Chat API вместо статичной `PREMIUM_URL`; из текста отказа в медиа убрана ссылка на сообщество. Причина: оплата должна узнавать пользователя без email. Зависит от маршрута `premium/link` ветки `payments` vk-bot; без него работает запасная статичная ссылка. Проверки: `compileall`, smoke-скрипт с подменённым Chat API. Живой VK и настоящий Chat API не проверены, не задеплоено.

## 2026-10-31 — оркестрация и фиксация контекста

Добавлены .codex/config.toml и explorer/planner/developer/reviewer/reporter, правила routing и workflow в AGENTS.md. Модель planner/reviewer — gpt-6-astra/high по подтверждённому выбору пользователя. Обновлены правила и память; контекст и конфигурация сохраняются отдельным локальным коммитом без прикладных изменений и push. Проверки: 42 TOML, строгая загрузка конфигураций в 7 корнях, diff check, reviewer PASS; mobile typecheck прошёл. Запуск всех ролей и ESLint не проверены (ESLint не настроен).

## 2026-10-31 — локальный контекст репозитория

Добавлены PROJECT, ARCHITECTURE, CONVENTIONS, CURRENT_TASK, STATE и CHANGELOG в .ai/; AGENTS.md направляет к ним будущие сессии. Комплект описывает именно dating-bot-vk и не требует соседних репозиториев для начала работы. Существующие инструкции сохранены.

Код и деплой не менялись. Проверки контекста и ограничения отражены в [STATE.md](STATE.md).

Историческая точка исходников: `master` / `c939c47`. Это не подтверждение деплоя или отсутствия незакоммиченных изменений.

## Формат следующих записей

Дата, изменение и причина, затронутые контракты, коммит/файлы и реальные проверки. Текущие планы хранить в CURRENT_TASK; актуальные ограничения — в STATE.

## 2026-11-12 — Пошлый чат только с премиумом

`api_client.search(peer, mode=None)` шлёт `{"mode":"adult"}` только при заданном mode; 403 на search → `NotPremiumError`. `handle_dating_find` ищет в режиме adult, при 403 показывает экран премиума; режим последнего поиска хранится в `handlers._search_modes` и сохраняется для «Следующий собеседник», обычный поиск его сбрасывает. flow.yaml: `dating_find.next: chat` (+ комментарий про 403 → premium), тексты не менялись. Снимок эквивалентности обновлён только для входов «Пошлый чат». Тесты `tests/test_adult_chat.py`; `unittest discover` — 109 OK.
