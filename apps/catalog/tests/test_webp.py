"""
Тесты WebP-копий.

Главное, что здесь стережётся, — работа на хранилище без пути на диске.
Именно так ведёт себя Cloudflare R2, и именно там конвертация раньше
пропускалась целиком: в продакшене копий не появлялось вовсе, а фильтр
молча отдавал оригиналы. Локальный диск проверяется заодно, но он и раньше
работал.
"""

import io

from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.test import TestCase
from PIL import Image

from apps.catalog.webp import convert_field, webp_name


def jpeg_bytes(size=(600, 900)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (30, 90, 60)).save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


class MemoryStorage(Storage):
    """
    Хранилище в памяти, у которого нет пути на диске.

    path() выбрасывает NotImplementedError — как у django-storages для S3
    и R2. Пока конвертация опиралась на field.path, на таком хранилище она
    не запускалась.
    """

    def __init__(self):
        self.files = {}

    def _open(self, name, mode="rb"):
        return ContentFile(self.files[name])

    def _save(self, name, content):
        self.files[name] = content.read()
        return name

    def exists(self, name):
        return name in self.files

    def url(self, name):
        return f"https://bucket.example/{name}"

    def path(self, name):
        raise NotImplementedError("хранилище без пути на диске")


class FakeField:
    """Минимум от ImageFieldFile, который нужен конвертации."""

    def __init__(self, name, storage):
        self.name = name
        self.storage = storage


class WebpConversionTests(TestCase):
    def setUp(self):
        self.storage = MemoryStorage()
        self.storage.files["posters/film.jpg"] = jpeg_bytes()
        self.field = FakeField("posters/film.jpg", self.storage)

    def test_creates_copy_on_storage_without_disk_path(self):
        result = convert_field(self.field)

        self.assertEqual(result, "posters/film.webp")
        self.assertTrue(self.storage.exists("posters/film.webp"))

    def test_copy_is_smaller_than_original(self):
        """Смысл конвертации — вес. Если копия не легче, она не нужна."""
        convert_field(self.field)

        original = len(self.storage.files["posters/film.jpg"])
        copy = len(self.storage.files["posters/film.webp"])
        self.assertLess(copy, original)

    def test_second_call_does_not_rewrite(self):
        convert_field(self.field)
        first = self.storage.files["posters/film.webp"]

        self.assertEqual(convert_field(self.field), "posters/film.webp")
        self.assertIs(self.storage.files["posters/film.webp"], first)
        self.assertEqual(len(self.storage.files), 2)

    def test_gif_is_left_alone(self):
        """Анимация в WebP теряется, а статичный кадр — уже не та картинка."""
        self.storage.files["posters/animated.gif"] = b"GIF89a-not-really"
        field = FakeField("posters/animated.gif", self.storage)

        self.assertIsNone(convert_field(field))
        self.assertNotIn("posters/animated.webp", self.storage.files)

    def test_broken_file_does_not_raise(self):
        """
        Битая картинка не должна ронять сохранение записи: копия — это
        оптимизация, а не условие того, что фильм существует.
        """
        self.storage.files["posters/broken.jpg"] = "это не картинка".encode("utf-8")
        field = FakeField("posters/broken.jpg", self.storage)

        self.assertIsNone(convert_field(field))

    def test_empty_field_is_ignored(self):
        self.assertIsNone(convert_field(FakeField("", self.storage)))


class WebpNameTests(TestCase):
    def test_replaces_suffix(self):
        self.assertEqual(webp_name("posters/2026/08/a.jpg"), "posters/2026/08/a.webp")
        self.assertEqual(webp_name("a.PNG"), "a.webp")
