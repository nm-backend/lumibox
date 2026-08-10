"""
Создание администратора при выкладке — без пароля в репозитории.

Пароль задаёт тот, кто разворачивает проект, переменной окружения.
Команда его не придумывает, не печатает и никуда не сохраняет: попади
он в вывод, он осел бы в логах сборки и в истории CI.

Запуск (в entrypoint или руками):
    DJANGO_SUPERUSER_EMAIL=you@example.com \\
    DJANGO_SUPERUSER_PASSWORD='...' \\
    python manage.py bootstrap_admin

Повторный запуск безопасен: существующего администратора команда не
трогает и пароль ему не меняет — иначе каждый деплой втихую сбрасывал бы
пароль, который владелец успел поменять руками.
"""

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    help = "Создаёт администратора по переменным окружения. Повторный запуск ничего не портит."

    def add_arguments(self, parser):
        parser.add_argument(
            "--promote",
            action="store_true",
            help="Выдать права администратора существующему пользователю с этой почтой.",
        )

    def handle(self, *args, **options):
        email = (os.environ.get("DJANGO_SUPERUSER_EMAIL") or "").strip().lower()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD") or ""
        username = (os.environ.get("DJANGO_SUPERUSER_USERNAME") or "").strip()

        # Почты нет — администратора не просили. Это не ошибка: выкладка
        # без создания админа должна проходить молча.
        if not email:
            self.stdout.write("DJANGO_SUPERUSER_EMAIL не задан — администратор не создаётся.")
            return

        existing = User.objects.filter(email=email).first()
        if existing is not None:
            if options["promote"] and not (existing.is_staff and existing.is_superuser):
                existing.is_staff = existing.is_superuser = True
                existing.save(update_fields=["is_staff", "is_superuser"])
                self.stdout.write(self.style.SUCCESS(f"Права администратора выданы: {email}"))
                return
            # Пароль намеренно не трогаем.
            self.stdout.write(f"Администратор уже существует: {email} — оставляю как есть.")
            return

        if not password:
            raise CommandError(
                "DJANGO_SUPERUSER_PASSWORD не задан. Пароль задаёте вы при выкладке — "
                "команда его не придумывает."
            )

        try:
            validate_password(password)
        except ValidationError as error:
            # Сообщаем, ЧТО не так, но сам пароль в вывод не попадает.
            raise CommandError("Пароль слишком слабый: " + "; ".join(error.messages)) from error

        User.objects.create_superuser(
            email=email,
            username=username or email.split("@")[0],
            password=password,
        )
        self.stdout.write(self.style.SUCCESS(f"Администратор создан: {email}"))
