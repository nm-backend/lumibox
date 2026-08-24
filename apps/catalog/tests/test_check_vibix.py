"""Tests for the check_vibix management command."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings


class CheckVibixCommandTests(TestCase):
    @override_settings(VIBIX_API_TOKEN="", VIDEO_SERVICE_API_KEY="")
    def test_no_credentials_warns_but_succeeds(self):
        """Without credentials, command warns but exits cleanly (exit code 0)."""
        out = StringIO()
        # Явно пустые настройки и запрет живого логина: иначе тест ловил бы
        # реальные креды машины (.env) и ходил бы в сеть.
        with patch("apps.catalog.video_service_api.login_vibix", return_value={}):
            call_command("check_vibix", stdout=out, stderr=StringIO())
        output = out.getvalue()
        self.assertIn("API Token", output)
        self.assertIn("не задан", output)

    @override_settings(
        VIBIX_API_TOKEN="test-token-12345678",
        VIBIX_PUBLISHER_ID="678503345",
    )
    @patch("apps.catalog.management.commands.check_vibix.iter_video_links")
    def test_with_credentials_shows_ok(self, mock_iter):
        """With valid-length credentials and working API, all checks pass."""
        # Each call to iter_video_links returns a fresh iterator
        def make_iter(*args, **kwargs):
            return iter(
                [{"embed_code": 'data-id="12345"', "type": "movie"}]
            )
        mock_iter.side_effect = make_iter
        out = StringIO()
        call_command("check_vibix", stdout=out, stderr=StringIO())
        output = out.getvalue()
        self.assertIn("OK", output)
        self.assertIn("токен задан", output)
        self.assertIn("data-id=12345", output)

    @override_settings(VIBIX_API_TOKEN="short")
    def test_short_token_fails(self):
        """Token shorter than 10 chars is rejected."""
        out = StringIO()
        err = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command("check_vibix", stdout=out, stderr=err)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("СБОЙ", out.getvalue())

    @override_settings(VIBIX_PUBLISHER_ID="not-a-number")
    def test_non_numeric_publisher_id_fails(self):
        """Publisher ID must be numeric."""
        out = StringIO()
        err = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command("check_vibix", stdout=out, stderr=err)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("СБОЙ", out.getvalue())

    @override_settings(VIBIX_API_TOKEN="", VIDEO_SERVICE_API_KEY="", VIBIX_PUBLISHER_ID="")
    def test_all_empty_shows_warnings_not_errors(self):
        """With all empty, 4 warnings, 0 failures, exit code 0."""
        out = StringIO()
        err = StringIO()
        # Тот же запрет живого логина: тест не зависит от окружения машины.
        with patch("apps.catalog.video_service_api.login_vibix", return_value={}):
            call_command("check_vibix", stdout=out, stderr=err)
        output = out.getvalue()
        self.assertIn("Предупреждений: 4", output)
        self.assertNotIn("СБОЙ", output)
