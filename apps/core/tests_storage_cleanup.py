"""Тесты очистки media-файлов при удалении записей и кэш-заголовков раздачи."""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.signals import request_finished
from django.db import close_old_connections
from django.test import TestCase
from PIL import Image

from apps.core.storage_cleanup import delete_field_file
from apps.core.test_factories import create_title, create_user


def make_png(width, height, name="test.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class DeleteFieldFileTests(TestCase):
    def setUp(self):
        self.title = create_title()
        self.title.poster.save("poster.png", make_png(600, 900), save=True)
        self.poster_name = self.title.poster.name

    def tearDown(self):
        self.title.poster.delete(save=False)

    def test_removes_file_and_webp_copy(self):
        storage = self.title.poster.storage

        from apps.catalog.webp import _get_webp_path

        webp_name = _get_webp_path(self.poster_name)
        storage.save(webp_name, io.BytesIO(b"fake-webp"))

        delete_field_file(self.title.poster)

        self.assertFalse(storage.exists(self.poster_name))
        self.assertFalse(storage.exists(webp_name))

    def test_missing_file_is_silent(self):
        # Поле без файла и файл, которого нет в хранилище, — не ошибка.
        delete_field_file(self.title.backdrop)
        self.title.poster.delete(save=False)
        delete_field_file(self.title.poster)


class PostDeleteCleanupTests(TestCase):
    def test_title_delete_removes_poster_files(self):
        title = create_title()
        title.poster.save("poster.png", make_png(600, 900), save=True)
        poster_name = title.poster.name
        storage = title.poster.storage
        self.assertTrue(storage.exists(poster_name))

        title.delete()

        self.assertFalse(storage.exists(poster_name))

    def test_user_delete_removes_avatar(self):
        user = create_user()
        user.avatar.save("avatar.png", make_png(100, 100), save=True)
        avatar_name = user.avatar.name
        storage = user.avatar.storage
        self.assertTrue(storage.exists(avatar_name))

        user.delete()

        self.assertFalse(storage.exists(avatar_name))


class MediaServingTests(TestCase):
    """
    Раздача медиа: Range-запросы и защита путей.

    Здесь отключён close_old_connections, и без этого тесты не работают
    на PostgreSQL.

    Раздача отдаёт FileResponse. Закрываясь — явно или руками сборщика
    мусора, — такой ответ шлёт request_finished, а штатный обработчик
    закрывает соединения с базой. Для настоящего запроса это правильно:
    соединение и должно освободиться в конце. Внутри теста TestCase
    держит открытую транзакцию, и закрытое соединение обрывает её.

    Коварство в отложенности: непрочитанный ответ переживал свой тест
    и добирался сборщиком уже во время следующего — тот падал на первом
    же обращении к базе, в setUp, хотя сам ничего не нарушал. Поэтому
    обработчик снимаем на весь класс, а не на отдельный тест: к моменту
    setUp соединение бывало закрыто заранее.

    Вторая половина решения — закрывать каждый ответ (см. _drain).
    Тогда ни один FileResponse не доживает до чужого теста.

    На SQLite ничего этого не видно: соединение переживает закрытие,
    и локальный прогон оставался зелёным, пока CI на PostgreSQL валился
    шестью ошибками. Боевая раздача не меняется.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        request_finished.disconnect(close_old_connections)

    @classmethod
    def tearDownClass(cls):
        request_finished.connect(close_old_connections)
        super().tearDownClass()

    def setUp(self):
        self.title = create_title()
        self.title.poster.save("poster.png", make_png(600, 900), save=True)
        self.url = self.title.poster.url

    def tearDown(self):
        self.title.poster.delete(save=False)

    def _drain(self, response):
        """Читает тело потокового ответа и закрывает его.

        Закрыть обязательно: иначе дескриптор файла и сам ответ доживают
        до следующего теста и рвут ему соединение с базой.
        """
        body = b"".join(response.streaming_content)
        response.close()
        return body

    def test_media_response_has_cache_control(self):
        response = self.client.get(self.url)
        self._drain(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "public, max-age=86400")

    def test_private_media_path_blocked(self):
        response = self.client.get("/media/private_media/x.mp4")
        self.assertEqual(response.status_code, 404)

    def test_path_traversal_blocked(self):
        response = self.client.get("/media/../manage.py")
        self.assertEqual(response.status_code, 404)

    def test_range_request_returns_206(self):
        response = self.client.get(self.url, HTTP_RANGE="bytes=0-99")

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertIn("bytes 0-99/", response["Content-Range"])
        self.assertEqual(response["Content-Length"], "100")

        self.assertEqual(len(self._drain(response)), 100)

    def test_open_ended_range(self):
        response = self.client.get(self.url, HTTP_RANGE="bytes=100-")

        self.assertEqual(response.status_code, 206)
        self.assertIn("bytes 100-", response["Content-Range"])

        self.assertGreater(len(self._drain(response)), 0)

    def test_suffix_range(self):
        response = self.client.get(self.url, HTTP_RANGE="bytes=-50")
        body = self._drain(response)

        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(body), 50)
        total = self.title.poster.storage.size(self.title.poster.name)
        self.assertEqual(response["Content-Range"], f"bytes {total - 50}-{total - 1}/{total}")

    def test_unsatisfiable_range_returns_416(self):
        total = self.title.poster.storage.size(self.title.poster.name)
        response = self.client.get(self.url, HTTP_RANGE=f"bytes={total}-")

        self.assertEqual(response.status_code, 416)
        self.assertEqual(response["Content-Range"], f"bytes */{total}")
