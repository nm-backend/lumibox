# lumibox — Project Journal

Persistence anchor for this workspace's agent memory. The agent maintains this file:
append notable decisions, changes, and session notes so they survive across chats and
sessions. Newest entries on top. `get_project_briefing` reads the sections below.

## About

LumiBox is a full-featured online cinema and media portal built with Django, featuring multi-source video playback (Vibix external player SDK, YouTube fallback player, and byte-range local video player), rich catalog filtering, ratings, user reviews, collections, and mobile-first responsive design.

## Team Setup

### Quick Start (одна команда)
```bash
./start.sh          # macOS/Linux (Docker или Podman)
# или
start.bat           # Windows (Docker Desktop)
```

Скрипт сам: проверяет Docker/Podman, создаёт `.env` с сгенерированными паролями,
поднимает контейнеры, применяет миграции, наполняет каталог demo-данными.

### Ручной запуск (Podman на Fedora с SELinux)
```bash
# 1. .env уже должен быть в корне (см. .env.example)
# 2. Поднять контейнеры:
set -a && source .env && set +a && podman-compose up --build -d
# 3. Проверить:
podman-compose ps          # все 4 контейнера Up
podman-compose logs web    # entrypoint: миграции → каталог → админ
```

### Ключевые порты
| Сервис     | URL                              |
|------------|----------------------------------|
| Сайт       | http://localhost:8001/            |
| Админка    | http://localhost:8001/admin/      |
| Swagger    | http://localhost:8001/api/docs/   |
| PostgreSQL | localhost:5433 (user: lumibox)    |
| Redis      | localhost:6380                    |

### Важно для Fedora/SELinux
В `docker-compose.yml` volume mounts используют суффикс `:z` —
без него rootless Podman не может прочитать bind-mounted файлы.
Не удаляйте `:z` из volume definitions!

## Recent Changes

- **Исправление плеера Vibix на продакшене**: найдена главная причина неработающего плеера — у многих фильмов в базе данных было заполнено поле `player_id`, но поле `player_type` было пустым. Без `player_type` логика `_get_external_player()` не может определить тип плеера, и плеер не работает. Добавлена management команда `fix_player_types.py` для автоматического исправления: она находит все записи с `player_id` но без `player_type` и заполняет `player_type` на основе поля `is_series` (movie для фильмов, series для сериалов). Проверено на продакшене: после установки `player_type="movie"` для "Дьявол носит Prada 2" плеер начал работать корректно.
- **Исправление SDK плеера Vibix**: удалён глобальный тестовый тег из `base.html` (data-id="8036", data-type="series"), который конфликтовал с реальными плеерами на страницах фильмов. SDK Vibix находил этот глобальный тег вместо конкретных плееров, что вызывало ошибку "Извините, запрашиваемый контент ещё не добавлен". Также исправлена загрузка SDK: согласно инструкции должен быть один скрипт без `async`, а резервный скрипт `alt.graphicslab.io` должен загружаться динамически через JavaScript при ошибке. Теперь в `base.html` только основной скрипт `graphicslab.io` без `async`, а резервный загружается через `vibix-player.js` при сбое. Проверено: теги плеера рендерятся с правильными параметрами (player_id, player_type, publisher_id), старый тестовый тег отсутствует.
- **Полный каталог в локальной dev-БД + починка авто-логина Vibix**: правка `config/settings/base.py` — добавлены `VIBIX_USERNAME`/`VIBIX_PASSWORD` в `env.Env()` и проброс в settings; раньше `login_vibix()` не мог получить креды из `.env`, и документированный auto-fallback токена никогда не работал. Плюс ротация протухшего `VIBIX_API_TOKEN` в `.env` через `login_vibix()`. После этого локально импортирован весь каталог издателя (`sync_vibix --create-missing`, возобновляемым запуском после сетевого обрыва): 29 941 запись, DRAFT по умолчанию, `player_id` заполнен у 29 940/29 941 (единственная без — «Одна ночь», kp 5509288: на стороне Vibix embed-данных плеера нет вообще).
- **Массовый импорт каталога Vibix (`--create-missing`)**: новый режим в `sync_vibix` обходит весь список издателя и создаёт отсутствующие записи. Дедуп по kp_id (снимок + частичный уникальный индекс `title_kp_id_uniq_when_filled`, миграция 0026 с дедупликацией старых дублей), батчи по 500 через bulk_create, блокировка от параллельных прогонов (`VideoServiceSyncState.locked_at`, TTL 12 ч, `--unlock`), DRAFT по умолчанию, постеры через URL-поля `poster_url/backdrop_url` (без скачивания), серверный фильтр `type movie|serial` в клиенте, dry-run, прогресс, детальный отчёт, Celery-задача `create_missing_catalog`. Ядро: `bulk_create_from_catalog()` в `video_service_sync.py`. Проверено: 821 тест, ruff/mypy чистые, масштабный тест 5000 записей ≈2500 зап/с, возобновление после обрыва, живой импорт страниц каталога.
- **Секреты**: из `.env.example` удалён реальный Vibix-токен (считать скомпрометированным — ротировать!), исправлен `VIBIX_API_BASE_URL` на `https://api.vibix.org/api/v1`.
- **Vibix Integration & Auto-Recovery**: Refreshed Vibix API bearer token authentication, implemented `login_vibix` automatic authentication fallback, sanitized `fetch_video_links` limit parameter (20, 50, 100), and added graceful fallback from 403 detail endpoints to `/videos/links` catalog lookup.
- **Sync Architecture Hardening**: Updated `sync_title` in `apps/catalog/video_service_sync.py` to extract `player_id` from `embed_code` and sync series seasons/episodes seamlessly.
- **Automated Verification**: Added comprehensive test suite `apps/catalog/tests/test_vibix_e2e.py` and Playwright browser E2E test `tests_e2e_playwright.js` verifying player gate button, SDK injection, and 6 mobile viewports (320px–1440px) with zero overflow.

## Session Memory

- Vibix API base URL: `https://api.vibix.org/api/v1`
- Publisher ID: `678503345` (User ID `1184`)
- Catalog size: 31,037 titles in `/publisher/videos/links`; заметная доля карточек без `kp_id` (~45% на первых страницах) — при массовом импорте они честно пропускаются
- Rendex SDK URL: `https://graphicslab.io/sdk/v2/rendex-sdk.min.js`
- Тесты `check_vibix` требуют герметичности: без override пустых кредов и патча `login_vibix` они подхватывают реальные данные `.env` и ходят в сеть

### Session 2026-09-11 — Исправление плеера Vibix на продакшене
- Диагноз главной проблемы: на продакшене lumibox.site плеер не работал, потому что у многих фильмов в базе данных было заполнено поле `player_id`, но поле `player_type` было пустым. Без `player_type` логика `_get_external_player()` в `views.py` не может определить тип плеера, и плеер не загружается.
- Проверка через админку lumibox.site: у фильма "Дьявол носит Prada 2" было `player_id="686838"` но `player_type=""`. После установки `player_type="movie"` плеер начал работать корректно.
- Исправление: добавлена management команда `fix_player_types.py` для автоматического исправления всех записей с `player_id` но без `player_type`. Команда заполняет `player_type` на основе поля `is_series` (movie для фильмов, series для сериалов).
- Команда запушена в репозиторий, GitHub Actions автоматически задеплоит на продакшен. После деплоя нужно выполнить `python manage.py fix_player_types` на продакшене.

### Session 2026-09-11 — Исправление SDK плеера Vibix
- Диагноз главной проблемы: в `base.html` был глобальный тестовый тег Vibix `<ins data-publisher-id="678503345" data-type="series" data-id="8036" ...></ins>`, который конфликтовал с реальными плеерами на страницах фильмов. SDK Vibix находил этот глобальный тег вместо конкретных плееров, что вызывало ошибку "Извините, запрашиваемый контент ещё не добавлен".
- Дополнительная проблема: в `base.html` были два скрипта SDK с `async` (основной и резервный), что нарушало инструкцию. Согласно инструкции должен быть один скрипт без `async`, а резервный должен загружаться динамически через JavaScript при ошибке.
- Исправления: (1) Удалён глобальный тестовый тег из `base.html`; (2) Оставлен только основной скрипт `graphicslab.io` без `async`; (3) Резервный скрипт `alt.graphicslab.io` загружается через `vibix-player.js` при сбое основного.
- Проверка: тестирование страницы фильма показало, что теги плеера рендерятся с правильными параметрами (player_id, player_type, publisher_id), старый тестовый тег отсутствует.

### Session 2026-09-06 — Полный импорт каталога в dev и авто-логин Vibix
- Диагноз двух крахов `sync_vibix`: (1) контейнеры Docker были подняты (демон Docker Desktop не запущен) → connection timeout на localhost:5433; (2) `VIBIX_API_TOKEN` в .env протух (401) → авто-логин не срабатывал, т.к. settings не читали `VIBIX_USERNAME`/`VIBIX_PASSWORD`. Оба исправлены.
- Правка `config/settings/base.py`: добавлены `VIBIX_USERNAME=(str, "")`, `VIBIX_PASSWORD=(str, "")` в `env.Env()` и проброс `VIBIX_USERNAME = env(...)` / `VIBIX_PASSWORD = env(...)` рядом с Vibix-блоком. Мypy/ruff: изменённый файл чист (mypy падает на предсуществующем `apps/core/py314_compat.py:30 cannot assign to a method` — не наше).
- Актуальный размер каталога: 31 964 карточки в `/videos/links` (320 страниц по 100). Импорт: создано 29 940 записей суммарно (первый заход: 16 000 до сетевого обрыва на ~177-й странице; повторный resumable-заход: ещё 13 940, `--create-missing` идемпотентен). Без kp_id пропущено 1 953, без года — 70, ошибок API — 0. Все записи созданы DRAFT; на сайте по-прежнему опубликована 1 карточка.
- `player_id` заполняется прямо в массовом импорте из embed_code — отдельный `--full` практически не нужен после `--create-missing` (29 940/29 941).
- Троттлинг Vibix в пике: страница отвечает до ~14 с; полный обход (320 страниц) занимает десятки минут. Ретраи с экспоненциальной паузой отрабатывают, но сетевой обрыв всё равно возможен — импорт перезапускается без потерь.
- **Серии сериалов**: все 7 227 сериалов имеют kp_id. `sync_vibix --episodes` ходит в detail-эндпоинт per-сериал (~2.7 с/сериал → полный проход ~4-5 ч). Идемпотентен: пары «сезон+серия» не дублируются, повторный запуск безопасен. Валидация на 20 сериалах: создано 229 серий, 0 ошибок. Полный прогон запущен 2026-09-06 ~14:36 (PID 26756, лог episodes_full.out, прогресс по `select count(*) from catalog_episode`).

### Session 2026-08-24 — Массовый импорт каталога
- Реализован `sync_vibix --create-missing` (см. Recent Changes) по утверждённому плану: без второй архитектуры, расширение существующего sync-слоя.
- Миграция `0026_title_poster_urls_kp_uniq_import_lock`: poster_url/backdrop_url у Title, locked_at у VideoServiceSyncState, RunPython-дедупликация kp_id перед частичным unique-индексом.
- Общий модуль `apps/catalog/translit.py` (кириллица→латиница), используется import_titles и массовым импортом.
- Урок: `IntegrityError` после успешного `bulk_create` внутри общего savepoint приводил к ложному учёту «created как skipped» — вставка записей и связка жанров/стран разделены по транзакциям; регрессионный тест добавлен.
- Урок: SQLite не умеет case-insensitive сравнение кириллицы (`iexact`) — в dev возможны регистровые дубли справочников жанров/стран; на проде PostgreSQL работает корректно.
- Живая проверка: `check_vibix` все OK; dry-run и реальный импорт страниц каталога прошли, повторный запуск создаёт 0.

### Session 2026-08-21 — Командный запуск
- **SELinux fix**: добавлен суффикс `:z` к volume mounts в `docker-compose.yml` для совместимости с rootless Podman на Fedora (SELinux Enforcing). Без `:z` entrypoint.sh не читается контейнером.
- **start.sh**: добавлена поддержка Podman как fallback для Docker, исправлена генерация `$ADMINPASS`.
- **AGENTS.md**: добавлен раздел `Team Setup` с инструкциями запуска для команды.
- Локальный запуск через `env -i` + nohup работает, но для команды рекомендуется `podman-compose up --build -d`.

