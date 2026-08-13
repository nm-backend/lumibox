"""
Тесты стабильного cache-busting статики.

Раньше static_version был int(time.time()) — номер менялся каждую секунду,
и браузер перекачивал CSS/JS при каждом визите. Теперь версия считается
от mtime самого свежего файла в static/ и обязана быть стабильной между
запросами, меняясь только вместе с ассетами.
"""

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.core.context_processors import _cached_static_version, global_settings, static_version


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


class AdsNetworkContextTests(SimpleTestCase):
    """ads_network в контексте: флаг, publisher_id и форматы."""

    @override_settings(
        ADS_NETWORK_ENABLED=False,
        ADS_NETWORK_PUBLISHER_ID="123",
        ADS_NETWORK_ADD_TYPES="sticker,banners",
    )
    def test_disabled_flag(self):
        """Флаг false — реклама в контексте выключена, параметры на месте."""
        ctx = global_settings(None)["ads_network"]
        self.assertFalse(ctx["enabled"])
        self.assertEqual(ctx["publisher_id"], "123")
        self.assertEqual(ctx["add_types"], "sticker,banners")

    @override_settings(
        ADS_NETWORK_ENABLED=True,
        ADS_NETWORK_PUBLISHER_ID="678503345",
        ADS_NETWORK_ADD_TYPES="sticker,pcsticker,banners",
    )
    def test_enabled_flag(self):
        """Флаг true — контекст готов к рендеру тега <ins>."""
        ctx = global_settings(None)["ads_network"]
        self.assertTrue(ctx["enabled"])
        self.assertEqual(ctx["publisher_id"], "678503345")
        self.assertEqual(ctx["add_types"], "sticker,pcsticker,banners")
