#!/bin/sh
# Восстановление базы из дампа, созданного backup_db.sh.
#
#   DATABASE_URL=postgres://... ./scripts/restore_db.sh backups/moviehub_2026-07-22.sql.gz
#
# ВНИМАНИЕ: перезаписывает текущие данные. Требует подтверждения.
set -e

: "${DATABASE_URL:?Задайте DATABASE_URL}"
FILE="${1:?Укажите файл дампа .sql.gz}"
[ -f "$FILE" ] || { echo "Файл не найден: $FILE"; exit 1; }

printf "Восстановить %s в базу? Текущие данные будут перезаписаны [y/N] " "$FILE"
read -r answer
case "$answer" in
    [yY]) ;;
    *) echo "Отменено."; exit 1 ;;
esac

echo "Восстанавливаю..."
gunzip -c "$FILE" | psql "$DATABASE_URL"
echo "Готово."
