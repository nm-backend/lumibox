"""
Тесты стабильного cache-busting статики.

Версия считается по хешу MD5 содержимого CSS/JS файлов (не по mtime,
так как mtime в Docker bind mounts на macOS/Windows не всегда обновляется).
Версия стабильна между запросами, меняясь только вместе с ассетами.
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

    def test_version_is_short_hex_string(self):
        """Версия — короткая hex-строка (хеш содержимого), пригодная для ?v=."""
        version = static_version(None)["static_version"]
        self.assertIsInstance(version, str)
        self.assertEqual(len(version), 12)
        # Должна быть валидной hex-строкой (MD5[:12])
        int(version, 16)
        self.assertNotIn(" ", version)

    @patch("apps.core.context_processors.os.walk")
    def test_version_changes_when_content_changes(self, mock_walk):
        """Правка файла в static/ должна менять версию и инвалидировать кэш."""
        import os
        import shutil
        import tempfile

        # Создаём временные файлы с разным содержимым.
        # На Windows TemporaryDirectory.cleanup() падает с PermissionError,
        # если файл ещё открыт: Python 3.14 отдаёт handle в ORC, а Windows
        # не выпускает его мгновенно. Решение: явно удаляем файлы перед
        # выходом из контекста, а рmdir — best-effort.
        tmp = tempfile.mkdtemp(prefix="lumibox-staticver-test-")
        try:
            css1 = os.path.join(tmp, "a.css")
            css2 = os.path.join(tmp, "b.css")
            with open(css1, "w") as f:
                f.write("body{color:red}")
            with open(css2, "w") as f:
                f.write("body{color:blue}")

            mock_walk.return_value = [(tmp, (), ("a.css",))]
            _cached_static_version.cache_clear()
            first = _cached_static_version()

            mock_walk.return_value = [(tmp, (), ("b.css",))]
            _cached_static_version.cache_clear()
            second = _cached_static_version()

            self.assertNotEqual(first, second)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


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
