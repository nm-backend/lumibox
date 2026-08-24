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

- **UI-референс Kinogo-геометрия обязателен.** Зафиксирован в `FRONTEND.md` и Session Memory. Геометрия/плотность/ритм — как Kinogo; цвет/лого/шрифт — LumiBox. Не рестайлить существующие токены без явной задачи.


- **Массовый импорт каталога Vibix (`--create-missing`)**: новый режим в `sync_vibix` обходит весь список издателя и создаёт отсутствующие записи. Дедуп по kp_id (снимок + частичный уникальный индекс `title_kp_id_uniq_when_filled`, миграция 0026 с дедупликацией старых дублей), батчи по 500 через bulk_create, блокировка от параллельных прогонов (`VideoServiceSyncState.locked_at`, TTL 12 ч, `--unlock`), DRAFT по умолчанию, постеры через URL-поля `poster_url/backdrop_url` (без скачивания), серверный фильтр `type movie|serial` в клиенте, dry-run, прогресс, детальный отчёт, Celery-задача `create_missing_catalog`. Ядро: `bulk_create_from_catalog()` в `video_service_sync.py`. Проверено: 821 тест, ruff/mypy чистые, масштабный тест 5000 записей ≈2500 зап/с, возобновление после обрыва, живой импорт страниц каталога.
- **Секреты**: из `.env.example` удалён реальный Vibix-токен (считать скомпрометированным — ротировать!), исправлен `VIBIX_API_BASE_URL` на `https://api.vibix.org/api/v1`.
- **Vibix Integration & Auto-Recovery**: Refreshed Vibix API bearer token authentication, implemented `login_vibix` automatic authentication fallback, sanitized `fetch_video_links` limit parameter (20, 50, 100), and added graceful fallback from 403 detail endpoints to `/videos/links` catalog lookup.
- **Sync Architecture Hardening**: Updated `sync_title` in `apps/catalog/video_service_sync.py` to extract `player_id` from `embed_code` and sync series seasons/episodes seamlessly.
- **Automated Verification**: Added comprehensive test suite `apps/catalog/tests/test_vibix_e2e.py` and Playwright browser E2E test `tests_e2e_playwright.js` verifying player gate button, SDK injection, and 6 mobile viewports (320px–1440px) with zero overflow.

## Session Memory

### ОБЯЗАТЕЛЬНЫЙ UI-референс (2026-08-24)

Полный контракт: `FRONTEND.md` → раздел «геометрия Kinogo × брендинг LumiBox».

- Геометрия = Kinogo (container ~976, content ~640, sidebar ~331, header ~44–45, search ~240 / input 170×22, poster ~200, card gap 20, card pad 20 / 5–10, meta 8, menu ~22).
- Брендинг = LumiBox (цвет, лого, шрифт, акцент). Не копировать визуал Kinogo.
- Цепочка: Header → nav → container → sidebar+content → section → card → poster+meta → description → actions → footer.
- Не переписывать то, что уже в пропорциях. Конфликт «красиво vs геометрия» — геометрия.
- Не: огромные поля, случайные gap, разные кнопки одного типа, двойной padding контейнера, overflow-хаки, DOM ради CSS, ломка `data-*`.
- После frontend-правок: 320 / 360 / 375 / 390 / 414 / 480 / 768 / 1024 / 1280 / 1440 / 1920.
- Текущие токены геометрии (задача 2026-08-24): `--container-width: 976`, `--header-height: 48` (56 на ≤1024), `--sidebar-width: 331`, `--sidebar-gap: 12`, `--search-width: 240`, `--search-height: 32`. Внутренняя колонка = 976 (container max-width = 976 + 32 padding). Не сдвигать без новой явной задачи.

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

