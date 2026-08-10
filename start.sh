#!/bin/sh
# ЛОКАЛЬНЫЙ запуск через docker compose (macOS/Linux): поднимает базу,
# Redis и сайт на localhost. Это НЕ точка входа продакшена — там
# работает scripts/run_web.sh, который запускает gunicorn.
# LumiBox — запуск проекта одной командой (macOS, Linux).
# Windows-версия: start.bat
#
# Делает всё сам: проверяет Docker, создаёт .env со сгенерированными
# паролями, поднимает контейнеры. Миграции, наполнение каталога и обложки
# выполняет entrypoint внутри контейнера.

set -e
cd "$(dirname "$0")"

echo ""
echo "  LumiBox — запуск"
echo "  ================="
echo ""

# ---------- 1. Docker ----------
if ! docker info >/dev/null 2>&1; then
    echo "  [ОШИБКА] Docker не запущен."
    echo "  Запустите Docker Desktop и повторите."
    exit 1
fi
echo "  [OK] Docker запущен"

# ---------- 2. Файл .env ----------
if [ -f .env ]; then
    echo "  [OK] Файл .env уже есть — не трогаю"
else
    echo "  [..] Создаю .env и генерирую пароли..."
    SECRET=$(docker run --rm python:3.13-slim python -c "import secrets; print(secrets.token_urlsafe(50))")
    DBPASS=$(docker run --rm python:3.13-slim python -c "import secrets; print(secrets.token_hex(16))")

    cat > .env <<EOF
# Создан автоматически файлом start.sh. В git не попадает.

DJANGO_SECRET_KEY=$SECRET
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

DATABASE_URL=postgres://lumibox:$DBPASS@localhost:5433/lumibox
REDIS_URL=redis://localhost:6380/0

POSTGRES_USER=lumibox
POSTGRES_PASSWORD=$DBPASS
POSTGRES_DB=lumibox

# Администратор создастся при первом запуске. Пароль сгенерирован случайно
# и лежит только в этом файле (.env в .gitignore) — в репозиторий он не попадает.
DJANGO_SUPERUSER_EMAIL=admin@lumibox.local
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=$ADMINPASS
EOF
    echo "  [OK] Файл .env создан"
fi

# ---------- 3. Сборка и запуск ----------
echo ""
echo "  [..] Собираю и запускаю контейнеры (первый раз 2-5 минут)..."
echo ""
docker compose up --build -d

# ---------- 4. Ждём готовности ----------
echo ""
printf "  [..] Жду, пока сайт ответит"
attempt=0
until curl -s -o /dev/null http://localhost:8001/ 2>/dev/null; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 60 ]; then
        echo ""
        echo "  [ВНИМАНИЕ] Сайт не ответил за 2 минуты."
        echo "  Смотрите логи: docker compose logs web"
        exit 1
    fi
    printf "."
    sleep 2
done

echo ""
echo ""
echo "  ============================================"
echo "    Готово! Проект запущен."
echo "  ============================================"
echo ""
echo "    Сайт:      http://localhost:8001/"
echo "    Админка:   http://localhost:8001/admin/"
echo "    Swagger:   http://localhost:8001/api/docs/"
echo "    ReDoc:     http://localhost:8001/api/redoc/"
echo ""
echo "    Вход в админку — данные из файла .env"
echo ""
echo "    Остановить: docker compose stop"
echo ""
