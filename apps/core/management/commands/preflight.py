"""
Предполётная проверка боевого окружения.

Конфигурацию можно вычитать глазами, но работает она или нет — видно только
с настоящими ключами. Эта команда запускается после выкладки и проверяет
каждую внешнюю зависимость делом: не «переменная задана», а «соединение
открылось, файл записался и прочитался обратно».

Она отвечает на вопрос «почему не работает» до того, как его задаст
посетитель. Django check --deploy проверяет настройки; здесь — связи.

    python manage.py preflight

Возвращает ненулевой код, если хоть одна обязательная проверка не прошла:
годится как шаг в пайплайне выкладки.

Ничего не отправляет наружу: письмо не шлётся, только открывается соединение
с почтовым сервером. Тестовый файл в хранилище удаляется за собой.
"""

import socket
import uuid

from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class Check:
    """Результат одной проверки."""

    def __init__(self, name, ok, detail, required=True):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.required = required


class Command(BaseCommand):
    help = "Проверяет связь с базой, кэшем, хранилищем и почтой на боевых ключах."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-storage",
            action="store_true",
            help="Не писать тестовый файл в хранилище",
        )

    def handle(self, *args, **options):
        checks = [
            self._check_settings(),
            self._check_database(),
            self._check_migrations(),
            self._check_cache(),
            self._check_email(),
        ]
        if not options["skip_storage"]:
            checks.append(self._check_storage())

        failed = [check for check in checks if not check.ok and check.required]
        warned = [check for check in checks if not check.ok and not check.required]

        width = max(len(check.name) for check in checks)
        for check in checks:
            if check.ok:
                mark, style = "OK  ", self.style.SUCCESS
            elif check.required:
                mark, style = "СБОЙ", self.style.ERROR
            else:
                mark, style = "ВНИМ", self.style.WARNING
            self.stdout.write(style(f"[{mark}] {check.name.ljust(width)}  {check.detail}"))

        self.stdout.write("")
        if failed:
            self.stderr.write(
                self.style.ERROR(f"Не прошло обязательных проверок: {len(failed)}.")
            )
            # Ненулевой код: шаг выкладки должен остановиться здесь, а не
            # выпустить в мир наполовину рабочий сайт.
            raise SystemExit(1)

        tail = f" Предупреждений: {len(warned)}." if warned else ""
        self.stdout.write(self.style.SUCCESS(f"Окружение готово.{tail}"))

    # ---------- проверки ----------

    def _check_settings(self):
        problems = []
        if settings.DEBUG:
            problems.append("DEBUG включён")
        if not settings.ALLOWED_HOSTS:
            problems.append("ALLOWED_HOSTS пуст")
        key = settings.SECRET_KEY or ""
        if len(key) < 50 or key.startswith("django-insecure-"):
            problems.append("SECRET_KEY слабый или не задан")
        if problems:
            return Check("Настройки", False, "; ".join(problems))
        return Check("Настройки", True, "DEBUG выключен, домены и ключ заданы")

    def _check_database(self):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as error:
            return Check("База данных", False, f"{type(error).__name__}: {error}")
        return Check("База данных", True, f"соединение открыто ({connection.vendor})")

    def _check_migrations(self):
        """
        Неприменённые миграции — самая частая причина 500 сразу после выкладки:
        код уже новый, схема ещё старая.
        """
        try:
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        except Exception as error:
            return Check("Миграции", False, f"{type(error).__name__}: {error}")
        if plan:
            names = ", ".join(f"{m.app_label}.{m.name}" for m, _ in plan[:3])
            return Check("Миграции", False, f"не применено: {len(plan)} ({names}…)")
        return Check("Миграции", True, "все применены")

    def _check_cache(self):
        key = f"preflight:{uuid.uuid4().hex}"
        try:
            cache.set(key, "1", 30)
            value = cache.get(key)
            cache.delete(key)
        except Exception as error:
            return Check("Кэш", False, f"{type(error).__name__}: {error}")
        if value != "1":
            # Локальный кэш в памяти отвечает, но между воркерами не делится:
            # прогрев главной и счётчики поколений работать не будут.
            return Check("Кэш", False, "запись не читается обратно")
        backend = settings.CACHES["default"]["BACKEND"].rsplit(".", 1)[-1]
        return Check("Кэш", True, f"запись и чтение работают ({backend})")

    def _check_storage(self):
        name = f"preflight/{uuid.uuid4().hex}.txt"
        try:
            saved = default_storage.save(name, ContentFile(b"preflight"))
            with default_storage.open(saved, "rb") as handle:
                content = handle.read()
            url = default_storage.url(saved)
            default_storage.delete(saved)
        except Exception as error:
            return Check("Хранилище", False, f"{type(error).__name__}: {error}")
        if content != b"preflight":
            return Check("Хранилище", False, "файл прочитан не тем, чем записан")
        backend = settings.STORAGES["default"]["BACKEND"].rsplit(".", 1)[-1]
        return Check("Хранилище", True, f"запись, чтение и удаление работают ({backend}); адрес: {url}")

    def _check_email(self):
        """
        Соединение с почтовым сервером — без отправки письма.

        Пока EMAIL_HOST пуст, письма печатаются в лог: сайт работает, но
        сброс пароля до человека не доходит. Это предупреждение, а не сбой:
        сайт без почты запускать можно, просто надо знать, что так и есть.
        """
        backend = settings.EMAIL_BACKEND
        if "smtp" not in backend:
            return Check(
                "Почта", False,
                "SMTP не настроен — письма пишутся в лог, сброс пароля не дойдёт",
                required=False,
            )
        try:
            from django.core.mail import get_connection

            connection_ = get_connection(fail_silently=False)
            connection_.open()
            connection_.close()
        except (OSError, socket.error) as error:
            return Check("Почта", False, f"{type(error).__name__}: {error}")
        except Exception as error:
            return Check("Почта", False, f"{type(error).__name__}: {error}")
        return Check("Почта", True, f"соединение с {settings.EMAIL_HOST} открыто")
