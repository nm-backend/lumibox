"""
Тесты строгого разбора ссылок YouTube.

Плеер MVP открывает только YouTube, поэтому границы проверяются
с двух сторон: все допустимые форматы должны дать ID, а всё остальное —
ссылки на другие сервисы, мусор и попытки протащить чужой код — None.
"""

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.catalog.youtube import (
    parse_youtube_id,
    validate_youtube_url,
    youtube_embed_url,
)

# Валидный ID: 11 символов [A-Za-z0-9_-].
VALID_ID = "dQw4w9WgXcQ"


class ParseYoutubeIdTests(TestCase):
    def test_watch_url(self):
        self.assertEqual(
            parse_youtube_id(f"https://www.youtube.com/watch?v={VALID_ID}"),
            VALID_ID,
        )

    def test_watch_url_without_www(self):
        self.assertEqual(
            parse_youtube_id(f"https://youtube.com/watch?v={VALID_ID}"),
            VALID_ID,
        )

    def test_watch_url_with_extra_params(self):
        self.assertEqual(
            parse_youtube_id(f"https://www.youtube.com/watch?v={VALID_ID}&t=42&list=abc"),
            VALID_ID,
        )

    def test_watch_url_http_scheme(self):
        self.assertEqual(
            parse_youtube_id(f"http://www.youtube.com/watch?v={VALID_ID}"),
            VALID_ID,
        )

    def test_youtu_be_short_url(self):
        self.assertEqual(parse_youtube_id(f"https://youtu.be/{VALID_ID}"), VALID_ID)

    def test_youtu_be_with_tracking_param(self):
        self.assertEqual(
            parse_youtube_id(f"https://youtu.be/{VALID_ID}?si=abc123"),
            VALID_ID,
        )

    def test_embed_url(self):
        self.assertEqual(
            parse_youtube_id(f"https://www.youtube.com/embed/{VALID_ID}"),
            VALID_ID,
        )

    def test_embed_url_with_query(self):
        self.assertEqual(
            parse_youtube_id(f"https://www.youtube.com/embed/{VALID_ID}?start=10"),
            VALID_ID,
        )

    def test_mobile_subdomain(self):
        self.assertEqual(
            parse_youtube_id(f"https://m.youtube.com/watch?v={VALID_ID}"),
            VALID_ID,
        )

    def test_v_and_shorts_legacy_formats(self):
        self.assertEqual(
            parse_youtube_id(f"https://www.youtube.com/v/{VALID_ID}"),
            VALID_ID,
        )
        self.assertEqual(
            parse_youtube_id(f"https://www.youtube.com/shorts/{VALID_ID}"),
            VALID_ID,
        )

    def test_other_domain_rejected(self):
        self.assertIsNone(parse_youtube_id("https://vimeo.com/123456"))
        self.assertIsNone(parse_youtube_id("https://rutube.ru/video/abc/"))

    def test_evil_youtube_lookalike_rejected(self):
        # Поддомен должен отделяться точкой — иначе «evil-youtube.com»
        # прошёл бы наивную проверку endswith("youtube.com").
        self.assertIsNone(parse_youtube_id(f"https://evil-youtube.com/watch?v={VALID_ID}"))
        self.assertIsNone(parse_youtube_id(f"https://youtube.com.evil.test/watch?v={VALID_ID}"))

    def test_malformed_urls_rejected(self):
        self.assertIsNone(parse_youtube_id("not a url"))
        self.assertIsNone(parse_youtube_id("youtube.com/watch?v="))
        self.assertIsNone(parse_youtube_id("https://www.youtube.com/"))

    def test_wrong_video_id_length_rejected(self):
        self.assertIsNone(parse_youtube_id("https://www.youtube.com/watch?v=short"))
        self.assertIsNone(
            parse_youtube_id("https://www.youtube.com/watch?v=this-id-is-way-too-long-ok")
        )

    def test_non_web_schemes_rejected(self):
        self.assertIsNone(parse_youtube_id("javascript:alert(1)//youtube.com/12345678901"))
        self.assertIsNone(parse_youtube_id("data:text/html,<script>alert(1)</script>"))
        self.assertIsNone(parse_youtube_id("javascript:https://www.youtube.com/watch?v=12345678901"))

    def test_xss_payload_rejected(self):
        # Попытка протащить разметку вместо ID — частый вид атаки.
        self.assertIsNone(
            parse_youtube_id('https://www.youtube.com/watch?v="><script>alert(1)</script>')
        )
        self.assertIsNone(parse_youtube_id("<script>alert(1)</script>"))

    def test_empty_and_none_rejected(self):
        self.assertIsNone(parse_youtube_id(""))
        self.assertIsNone(parse_youtube_id(None))
        self.assertIsNone(parse_youtube_id("   "))


class YoutubeEmbedUrlTests(TestCase):
    def test_builds_embed_from_watch(self):
        self.assertEqual(
            youtube_embed_url(f"https://www.youtube.com/watch?v={VALID_ID}"),
            f"https://www.youtube.com/embed/{VALID_ID}",
        )

    def test_builds_embed_from_youtu_be(self):
        self.assertEqual(
            youtube_embed_url(f"https://youtu.be/{VALID_ID}"),
            f"https://www.youtube.com/embed/{VALID_ID}",
        )

    def test_returns_none_for_foreign_domain(self):
        self.assertIsNone(youtube_embed_url("https://vimeo.com/123456"))


class ValidateYoutubeUrlTests(TestCase):
    def test_valid_passes(self):
        # Не бросает исключение.
        validate_youtube_url(f"https://www.youtube.com/watch?v={VALID_ID}")

    def test_empty_passes(self):
        validate_youtube_url("")

    def test_foreign_domain_raises(self):
        with self.assertRaises(ValidationError):
            validate_youtube_url("https://vimeo.com/123456")

    def test_malformed_raises(self):
        with self.assertRaises(ValidationError):
            validate_youtube_url("https://www.youtube.com/watch?v=broken")
