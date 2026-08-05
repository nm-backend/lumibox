"""
Тесты стабильного cache-busting статики.

Раньше static_version был int(time.time()) — номер менялся каждую секунду,
и браузер перекачивал CSS/JS при каждом визите. Теперь версия считается
от mtime самого свежего файла в static/ и обязана быть стабильной между
запросами, меняясь только вместе с ассетами.
"""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core.context_processors import _cached_static_version, static_version


class StaticVersionTests(SimpleTestCase):
    def tearDown(self):
        # lru_cache держит значение между тестами — сбрасываем.
        _cached_static_version.cache_clear()

    def test_returns_same_value_on_every_call(self):
        """Версия не должна меняться от запроса к запросу."""
        first = static_version(None)["static_version"]
        second = static_version(None)["static_version"]
        self.assertEqual(first, second)

    def test_version_is_short_stable_string(self):
        """Версия — короткая строка, пригодная для URL в ?v=."""
        version = static_version(None)["static_version"]
        self.assertIsInstance(version, str)
        self.assertTrue(version.startswith("m"))
        self.assertNotIn(" ", version)

    @patch("apps.core.context_processors.os.walk")
    @patch("apps.core.context_processors.os.path.getmtime")
    def test_version_changes_when_asset_changes(self, mock_mtime, mock_walk):
        """Правка файла в static/ должна менять версию и инвалидировать кэш."""
        mock_walk.return_value = [("static/css", (), ("base.css",))]
        mock_mtime.return_value = 1000.0
        first = _cached_static_version()

        mock_mtime.return_value = 2000.0
        _cached_static_version.cache_clear()
        second = _cached_static_version()

        self.assertNotEqual(first, second)
