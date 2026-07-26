"""
Автоматический бэкап базы данных.

Создаёт SQL-дамп базы и сохраняет его в указанную директорию.
Для PostgreSQL использует pg_dump, для SQLite — cp.

Запуск:
    python manage.py backup_database
    python manage.py backup_database --output /backups/

Для автоматического запуска добавить в cron:
    0 3 * * * cd /app && python manage.py backup_database
"""

import os
import shutil
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Создаёт бэкап базы данных."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=str(settings.BASE_DIR / "backups"),
            help="Директория для сохранения бэкапов",
        )

    def handle(self, *args, **options):
        output_dir = options["output"]
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        db_url = settings.DATABASES["default"]

        if db_url["ENGINE"] == "django.db.backends.postgresql":
            filename = f"backup_{timestamp}.sql"
            filepath = os.path.join(output_dir, filename)
            self._backup_postgres(db_url, filepath)
        elif db_url["ENGINE"] == "django.db.backends.sqlite3":
            filename = f"backup_{timestamp}.sqlite3"
            filepath = os.path.join(output_dir, filename)
            self._backup_sqlite(db_url["NAME"], filepath)
        else:
            self.stderr.write(f"Неподдерживаемый движок: {db_url['ENGINE']}")
            return

        size_mb = os.path.getsize(filepath) / 1024 / 1024
        self.stdout.write(self.style.SUCCESS(f"Бэкап создан: {filepath} ({size_mb:.1f} МБ)"))

    def _backup_postgres(self, db_config, filepath):
        """Бэкап PostgreSQL через pg_dump."""
        import subprocess

        cmd = [
            "pg_dump",
            "-h", db_config["HOST"],
            "-p", str(db_config["PORT"]),
            "-U", db_config["USER"],
            "-d", db_config["NAME"],
            "-f", filepath,
            "--no-owner",
            "--no-privileges",
        ]
        env = os.environ.copy()
        env["PGPASSWORD"] = db_config["PASSWORD"]
        subprocess.run(cmd, env=env, check=True, capture_output=True)

    def _backup_sqlite(self, db_path, filepath):
        """Бэкап SQLite через копирование файла."""
        shutil.copy2(db_path, filepath)
