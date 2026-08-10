"""Тесты очистки media-файлов при удалении записей и кэш-заголовков раздачи."""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
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

    Ответ здесь читают, но НЕ закрывают руками — и это принципиально.

    Раздача отдаёт FileResponse. Тест-клиент Django оборачивает его тело
    в closing_iterator_wrapper: дочитав итератор, обёртка сама закрывает
    ответ, предварительно сняв обработчик close_old_connections и вернув
    его на место (django/test/client.py). То есть закрытие уже сделано
    и сделано безопасно.

    Явный response.close() после этого шлёт request_finished второй раз,
    когда обработчик уже возвращён, — и тот закрывает соединение с базой.
    TestCase держит открытую транзакцию, она обрывается, а падает при этом
    не текущий тест, а следующий: на первом же обращении к базе в setUp.

    На SQLite ничего не видно — соединение переживает закрытие. На
    PostgreSQL это стоило шести ошибок в CI при полностью зелёном
    локальном прогоне.
    """

    def setUp(self):
        self.title = create_title()
        self.title.poster.save("poster.png", make_png(600, 900), save=True)
        self.url = self.title.poster.url

    def tearDown(self):
        self.title.poster.delete(save=False)

    def _drain(self, response):
        """Дочитывает тело потокового ответа.

        Закрывать не нужно и нельзя: обёртка тест-клиента закроет ответ
        сама, как только итератор кончится, и сделает это безопасно для
        соединения с базой. Лишний response.close() поверх — как раз то,
        что роняло CI на PostgreSQL.
        """
        return b"".join(response.streaming_content)

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
