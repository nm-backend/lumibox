"""
Тесты предполётной проверки.

Смысл команды — остановить выкладку, если внешняя зависимость не отвечает.
Значит, проверять надо ровно это: что сбой замечен и что код возврата
ненулевой. Команда, которая при неработающей базе рапортует «готово»,
хуже, чем её отсутствие.
"""

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings


def run():
    """Запускает команду и возвращает (вывод, код выхода)."""
    out, err = StringIO(), StringIO()
    try:
        call_command("preflight", stdout=out, stderr=err)
    except SystemExit as exit_code:
        return out.getvalue() + err.getvalue(), exit_code.code
    return out.getvalue() + err.getvalue(), 0


class PreflightTests(TestCase):
    def test_passes_on_healthy_environment(self):
        text, code = run()

        self.assertEqual(code, 0)
        self.assertIn("База данных", text)
        self.assertIn("Кэш", text)
        self.assertIn("Хранилище", text)

    @override_settings(DEBUG=True)
    def test_debug_on_is_a_failure(self):
        """DEBUG в продакшене показывает посетителю трассировки и настройки."""
        text, code = run()

        self.assertEqual(code, 1)
        self.assertIn("DEBUG включён", text)

    @override_settings(SECRET_KEY="django-insecure-short")
    def test_weak_secret_key_is_a_failure(self):
        text, code = run()

        self.assertEqual(code, 1)
        self.assertIn("SECRET_KEY", text)

    @override_settings(ALLOWED_HOSTS=[])
    def test_empty_allowed_hosts_is_a_failure(self):
        text, code = run()

        self.assertEqual(code, 1)
        self.assertIn("ALLOWED_HOSTS", text)

    def test_broken_cache_is_a_failure(self):
        """
        Кэш, который принимает запись и не отдаёт её обратно, — худший случай:
        сайт отвечает, но прогрев главной и счётчики поколений не работают,
        и заметить это по логам нельзя.
        """
        with mock.patch("apps.core.management.commands.preflight.cache.get", return_value=None):
            text, code = run()

        self.assertEqual(code, 1)
        self.assertIn("Кэш", text)

    def test_unreachable_storage_is_a_failure(self):
        with mock.patch(
            "apps.core.management.commands.preflight.default_storage.save",
            side_effect=OSError("бакет недоступен"),
        ):
            text, code = run()

        self.assertEqual(code, 1)
        self.assertIn("Хранилище", text)

    def test_storage_can_be_skipped(self):
        """
        Флаг нужен там, где писать в бакет на каждый деплой не хочется —
        например, в проверке из пайплайна на чужом окружении.
        """
        out = StringIO()
        call_command("preflight", "--skip-storage", stdout=out)

        self.assertNotIn("Хранилище", out.getvalue())

    def test_missing_smtp_warns_but_does_not_block(self):
        """
        Сайт без почты запускать можно — просто сброс пароля не дойдёт.
        Это повод предупредить, а не останавливать выкладку.
        """
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
        ):
            text, code = run()

        self.assertEqual(code, 0)
        self.assertIn("SMTP не настроен", text)
