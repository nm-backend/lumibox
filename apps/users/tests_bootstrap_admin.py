"""
Тесты команды bootstrap_admin.

Команда создаёт администратора при выкладке. Главное её свойство —
пароль задаёт владелец переменной окружения: команда его не придумывает,
не печатает и не меняет существующему администратору. Иначе пароль
осел бы в логах сборки, а каждая выкладка втихую сбрасывала бы тот,
что владелец успел поменять руками.
"""

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

User = get_user_model()

STRONG = "very-secret-pass-123"


class BootstrapAdminTests(TestCase):
    def run_command(self, **env):
        out = StringIO()
        with self.settings():
            import os

            saved = {k: os.environ.get(k) for k in
                     ("DJANGO_SUPERUSER_EMAIL", "DJANGO_SUPERUSER_PASSWORD", "DJANGO_SUPERUSER_USERNAME")}
            try:
                for key in saved:
                    os.environ.pop(key, None)
                os.environ.update({k: v for k, v in env.items() if v is not None})
                call_command("bootstrap_admin", stdout=out)
            finally:
                for key, value in saved.items():
                    os.environ.pop(key, None)
                    if value is not None:
                        os.environ[key] = value
        return out.getvalue()

    def test_without_email_does_nothing(self):
        """Выкладка без администратора должна проходить молча, а не падать."""
        output = self.run_command()

        self.assertIn("не задан", output)
        self.assertEqual(User.objects.count(), 0)

    def test_without_password_refuses(self):
        """Пароль не придумываем — иначе владелец не будет знать свой же."""
        with self.assertRaises(CommandError) as error:
            self.run_command(DJANGO_SUPERUSER_EMAIL="boss@lumibox.site")

        self.assertIn("DJANGO_SUPERUSER_PASSWORD", str(error.exception))
        self.assertEqual(User.objects.count(), 0)

    def test_weak_password_refused(self):
        with self.assertRaises(CommandError):
            self.run_command(
                DJANGO_SUPERUSER_EMAIL="boss@lumibox.site",
                DJANGO_SUPERUSER_PASSWORD="12345",
            )

        self.assertEqual(User.objects.count(), 0)

    def test_creates_superuser(self):
        self.run_command(
            DJANGO_SUPERUSER_EMAIL="Boss@LumiBox.com",
            DJANGO_SUPERUSER_PASSWORD=STRONG,
        )

        user = User.objects.get()
        # Почта приводится к нижнему регистру: вход идёт по ней.
        self.assertEqual(user.email, "boss@lumibox.com")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password(STRONG))

    def test_password_never_printed(self):
        """Вывод уходит в логи сборки — пароля там быть не должно."""
        output = self.run_command(
            DJANGO_SUPERUSER_EMAIL="boss@lumibox.site",
            DJANGO_SUPERUSER_PASSWORD=STRONG,
        )

        self.assertNotIn(STRONG, output)

    def test_second_run_creates_no_duplicate(self):
        for _ in range(2):
            self.run_command(
                DJANGO_SUPERUSER_EMAIL="boss@lumibox.site",
                DJANGO_SUPERUSER_PASSWORD=STRONG,
            )

        self.assertEqual(User.objects.filter(email="boss@lumibox.site").count(), 1)

    def test_existing_password_not_reset(self):
        """Владелец мог сменить пароль руками — выкладка не должна его затирать."""
        self.run_command(
            DJANGO_SUPERUSER_EMAIL="boss@lumibox.site",
            DJANGO_SUPERUSER_PASSWORD=STRONG,
        )
        user = User.objects.get()
        user.set_password("changed-by-owner-9876")
        user.save()

        self.run_command(
            DJANGO_SUPERUSER_EMAIL="boss@lumibox.site",
            DJANGO_SUPERUSER_PASSWORD=STRONG,
        )

        user.refresh_from_db()
        self.assertTrue(user.check_password("changed-by-owner-9876"))

    def test_promote_grants_rights_to_existing_user(self):
        User.objects.create_user(
            email="editor@lumibox.site", username="editor", password=STRONG
        )

        import os

        os.environ["DJANGO_SUPERUSER_EMAIL"] = "editor@lumibox.site"
        try:
            call_command("bootstrap_admin", "--promote", stdout=StringIO())
        finally:
            os.environ.pop("DJANGO_SUPERUSER_EMAIL", None)

        user = User.objects.get(email="editor@lumibox.site")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)


class AdminAccessTests(TestCase):
    """Созданный командой администратор действительно входит в админку."""

    def test_login_and_admin_pages(self):
        import os

        os.environ["DJANGO_SUPERUSER_EMAIL"] = "boss@lumibox.site"
        os.environ["DJANGO_SUPERUSER_PASSWORD"] = STRONG
        try:
            call_command("bootstrap_admin", stdout=StringIO())
        finally:
            os.environ.pop("DJANGO_SUPERUSER_EMAIL", None)
            os.environ.pop("DJANGO_SUPERUSER_PASSWORD", None)

        response = self.client.post(
            "/login/", {"username": "boss@lumibox.site", "password": STRONG}
        )
        self.assertEqual(response.status_code, 302)

        for url in [
            "/admin/",
            "/admin/catalog/title/add/",
            "/admin/catalog/voiceover/",
            "/admin/catalog/franchise/",
            "/admin/reviews/comment/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
