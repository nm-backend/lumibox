#!/bin/sh
# Резервная копия базы. Читает DATABASE_URL из окружения — тот же адрес,
# что использует приложение. Кладёт сжатый дамп с датой в BACKUP_DIR.
#
#   DATABASE_URL=postgres://... ./scripts/backup_db.sh
#   BACKUP_DIR=/backups DATABASE_URL=postgres://... ./scripts/backup_db.sh
set -e

: "${DATABASE_URL:?Задайте DATABASE_URL}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"

STAMP=$(date +%Y-%m-%d_%H-%M-%S)
FILE="$BACKUP_DIR/moviehub_$STAMP.sql.gz"

echo "Дамп базы -> $FILE"
pg_dump "$DATABASE_URL" | gzip > "$FILE"

# Держим последние 14 копий, старые удаляем — иначе диск однажды кончится.
ls -1t "$BACKUP_DIR"/moviehub_*.sql.gz 2>/dev/null | tail -n +15 | xargs -r rm --
echo "Готово. Копии в $BACKUP_DIR:"
ls -1t "$BACKUP_DIR"/moviehub_*.sql.gz | head -5
