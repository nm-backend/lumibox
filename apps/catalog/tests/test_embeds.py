"""
Тесты превращения ссылки на видеохостинг во встраиваемую.

Главное здесь не удобство, а безопасность: адрес вводит редактор, а мы
подставляем его в iframe. Незнакомый или подделанный хост не должен
туда попасть ни при каких обстоятельствах.
"""

from django.test import SimpleTestCase

from apps.catalog.embeds import get_embed_url


class KnownHostsTests(SimpleTestCase):
    def test_youtube_watch_link(self):
        self.assertEqual(
            get_embed_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
        )

    def test_youtube_short_link(self):
        self.assertEqual(
            get_embed_url("https://youtu.be/dQw4w9WgXcQ"),
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
        )

    def test_youtube_already_embed(self):
        self.assertEqual(
            get_embed_url("https://www.youtube.com/embed/dQw4w9WgXcQ"),
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
        )

    def test_vimeo(self):
        self.assertEqual(
            get_embed_url("https://vimeo.com/123456789"),
            "https://player.vimeo.com/video/123456789",
        )

    def test_rutube(self):
        self.assertEqual(
            get_embed_url("https://rutube.ru/video/deadbeef/"),
            "https://rutube.ru/play/embed/deadbeef",
        )


class SecurityTests(SimpleTestCase):
    """Всё, что не опознано как доверенный хост, встраиваться не должно."""

    def test_lookalike_domain_rejected(self):
        """
        Главная ловушка: «evil-youtube.com» заканчивается на «youtube.com».
        Наивная проверка через endswith пропустила бы чужой домен в iframe.
        """
        self.assertIsNone(get_embed_url("https://evil-youtube.com/watch?v=abc"))
        self.assertIsNone(get_embed_url("https://youtube.com.evil.test/watch?v=abc"))

    def test_javascript_scheme_rejected(self):
        self.assertIsNone(get_embed_url("javascript:alert(1)"))

    def test_data_scheme_rejected(self):
        self.assertIsNone(get_embed_url("data:text/html,<script>alert(1)</script>"))

    def test_unknown_host_returns_none(self):
        """Незнакомый хост — не ошибка: страница покажет обычную ссылку."""
        self.assertIsNone(get_embed_url("https://example.com/video/1"))

    def test_empty_and_broken_input(self):
        self.assertIsNone(get_embed_url(""))
        self.assertIsNone(get_embed_url(None))

    def test_subdomain_of_trusted_host_allowed(self):
        """Поддомен доверенного хоста — легитимен (m.youtube.com)."""
        self.assertEqual(
            get_embed_url("https://m.youtube.com/watch?v=dQw4w9WgXcQ"),
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
        )

    def test_vimeo_non_numeric_id_rejected(self):
        self.assertIsNone(get_embed_url("https://vimeo.com/not-a-number"))
