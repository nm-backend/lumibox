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

- **Vibix Integration & Auto-Recovery**: Refreshed Vibix API bearer token authentication, implemented `login_vibix` automatic authentication fallback, sanitized `fetch_video_links` limit parameter (20, 50, 100), and added graceful fallback from 403 detail endpoints to `/videos/links` catalog lookup.
- **Sync Architecture Hardening**: Updated `sync_title` in `apps/catalog/video_service_sync.py` to extract `player_id` from `embed_code` and sync series seasons/episodes seamlessly.
- **Automated Verification**: Added comprehensive test suite `apps/catalog/tests/test_vibix_e2e.py` (all 770 Django tests passing) and Playwright browser E2E test `tests_e2e_playwright.js` verifying player gate button, SDK injection, and 6 mobile viewports (320px–1440px) with zero overflow.

## Session Memory

- Vibix API base URL: `https://api.vibix.org/api/v1`
- Publisher ID: `678503345` (User ID `1184`)
- Catalog size: 31,037 titles in `/publisher/videos/links`
- Rendex SDK URL: `https://graphicslab.io/sdk/v2/rendex-sdk.min.js`

### Session 2026-08-21 — Командный запуск
- **SELinux fix**: добавлен суффикс `:z` к volume mounts в `docker-compose.yml` для совместимости с rootless Podman на Fedora (SELinux Enforcing). Без `:z` entrypoint.sh не читается контейнером.
- **start.sh**: добавлена поддержка Podman как fallback для Docker, исправлена генерация `$ADMINPASS`.
- **AGENTS.md**: добавлен раздел `Team Setup` с инструкциями запуска для команды.
- Локальный запуск через `env -i` + nohup работает, но для команды рекомендуется `podman-compose up --build -d`.

