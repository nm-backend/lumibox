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

- **Рефакторинг в стиле кино-портала + тёмная палитра плеера**: тег `<ins>` Vibix вынесен в `templates/includes/player.html` (design=1, тёмная кино-палитра `#181a1b/#ffffff/#2b2e31/#e94560/#111213`, добавлены `data-poster="true"` и `data-nopreload="true"`); Rendex SDK подключён глобально в `<head>` base.html (`async`, `referrerpolicy="no-referrer"`); в `vibix-player.js` возвращён reinit (`window.rendex.init/scan`) на клик «Начать». Сетка `.lb-contentwrap--home` инвертирована на контент слева (~75%)/сайдбар справа (~25%), контейнер 1200px. На главную добавлена карусель «Горячие новинки» (готовые `.carousel`). JSON-LD/OG используют `kp_rating`, `poster_url`, `og:type video.movie` и заголовок «…смотреть онлайн на LumiBox». Удалён скомпрометированный `VIBIX_API_TOKEN` из `docker-compose.prod.yml` (теперь обязательный `:?`), `VIBIX_API_BASE_URL` выправлен на `api.vibix.org`. Тесты: 608 passed + 45 subtests, ruff/mypy чистые.
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

