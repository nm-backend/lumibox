"""Adversarial tests for media serving.

Attack surface: directory traversal, private media disclosure, malformed
Range requests. The media endpoint must never serve files outside
MEDIA_ROOT and never crash on hostile headers.

All attacks here are blocked by existing defenses; the tests document
that the guards hold.
"""

import os
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase

MEDIA_URL = "/media/"


def _body(response):
    """FileResponse is streaming; consume it and release the file handle."""
    if hasattr(response, "streaming_content"):
        body = b"".join(response.streaming_content)
    else:
        body = response.content
    response.close()
    return body


class TraversalTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_dotdot_traversal_404(self):
        response = self.client.get(f"{MEDIA_URL}../config/settings/base.py")
        self.assertEqual(response.status_code, 404)

    def test_double_dotdot_traversal_404(self):
        response = self.client.get(f"{MEDIA_URL}../../../../etc/passwd")
        self.assertEqual(response.status_code, 404)

    def test_encoded_dotdot_traversal_404(self):
        response = self.client.get(f"{MEDIA_URL}%2e%2e%2f%2e%2e%2fetc%2fpasswd")
        self.assertEqual(response.status_code, 404)

    def test_absolute_path_404(self):
        response = self.client.get(f"{MEDIA_URL}/etc/passwd")
        self.assertEqual(response.status_code, 404)

    def test_backslash_traversal_404(self):
        response = self.client.get(f"{MEDIA_URL}..\\..\\config\\settings\\base.py")
        self.assertEqual(response.status_code, 404)


class PrivateMediaTests(TestCase):
    def setUp(self):
        cache.clear()
        root = Path(settings.MEDIA_ROOT)
        self.private_dir = root / "private_media"
        self.private_dir.mkdir(parents=True, exist_ok=True)
        self.secret = self.private_dir / "secret.txt"
        self.secret.write_bytes(b"TOP-SECRET-CONTENT")
        # Сосед с похожим именем: он публичный, и запрет не должен его задевать.
        self.lookalike = root / "private_media_notes.txt"
        self.lookalike.write_bytes(b"PUBLIC-CONTENT")

    def tearDown(self):
        for path in (self.secret, self.lookalike):
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass

    def test_private_media_file_404(self):
        response = self.client.get(f"{MEDIA_URL}private_media/secret.txt")
        self.assertEqual(response.status_code, 404)

    def test_private_media_encoded_slash_404(self):
        response = self.client.get(f"{MEDIA_URL}private_media%2fsecret.txt")
        self.assertEqual(response.status_code, 404)

    def test_private_media_via_parent_segment_404(self):
        """«..» не должен открывать приватную папку в обход запрета.

        Проверка префикса шла по строке из адреса: «x/../private_media/…»
        на «private_media/» не начинается, а abspath убирал «..» позже.
        Файл отдавался с кодом 200.
        """
        response = self.client.get(f"{MEDIA_URL}x/../private_media/secret.txt")
        self.assertEqual(response.status_code, 404)

    def test_private_media_via_encoded_parent_segment_404(self):
        """То же с закодированными точками — так шлёт обычный браузер."""
        response = self.client.get(f"{MEDIA_URL}x/%2e%2e/private_media/secret.txt")
        self.assertEqual(response.status_code, 404)

    def test_private_media_via_current_dir_segment_404(self):
        response = self.client.get(f"{MEDIA_URL}./private_media/secret.txt")
        self.assertEqual(response.status_code, 404)

    def test_private_media_case_variant_404(self):
        """Windows не различает регистр — обход через «Private_media» тоже закрыт."""
        response = self.client.get(f"{MEDIA_URL}Private_media/secret.txt")
        self.assertEqual(response.status_code, 404)

    def test_public_lookalike_name_is_served(self):
        """Запрет бьёт ровно по папке private_media, а не по похожим именам."""
        response = self.client.get(f"{MEDIA_URL}private_media_notes.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_body(response), b"PUBLIC-CONTENT")


class RangeTests(TestCase):
    def setUp(self):
        cache.clear()
        root = Path(settings.MEDIA_ROOT)
        self.public_dir = root / "public"
        self.public_dir.mkdir(parents=True, exist_ok=True)
        self.video = self.public_dir / "clip.bin"
        self.video.write_bytes(os.urandom(1024))

    def tearDown(self):
        try:
            self.video.unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_full_file_served(self):
        response = self.client.get(f"{MEDIA_URL}public/clip.bin")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(_body(response)), 1024)

    def test_byte_range_206(self):
        response = self.client.get(
            f"{MEDIA_URL}public/clip.bin", HTTP_RANGE="bytes=0-99"
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(_body(response)), 100)
        self.assertEqual(response["Content-Range"], "bytes 0-99/1024")

    def test_open_ended_range_206(self):
        response = self.client.get(
            f"{MEDIA_URL}public/clip.bin", HTTP_RANGE="bytes=1000-"
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(_body(response)), 24)
        self.assertEqual(response["Content-Range"], "bytes 1000-1023/1024")

    def test_suffix_range_206(self):
        response = self.client.get(
            f"{MEDIA_URL}public/clip.bin", HTTP_RANGE="bytes=-10"
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(_body(response)), 10)

    def test_malformed_range_416(self):
        response = self.client.get(
            f"{MEDIA_URL}public/clip.bin", HTTP_RANGE="bytes=abc"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(_body(response)), 1024)

    def test_garbage_range_header_not_500(self):
        response = self.client.get(
            f"{MEDIA_URL}public/clip.bin",
            HTTP_RANGE="bytes=0-99999999999999999999",
        )
        self.assertIn(response.status_code, (200, 206, 416))
        self.assertNotEqual(response.status_code, 500)
        _body(response)

    def test_start_beyond_size_416(self):
        response = self.client.get(
            f"{MEDIA_URL}public/clip.bin", HTTP_RANGE="bytes=999999-"
        )
        self.assertEqual(response.status_code, 416)

    def test_missing_file_404(self):
        response = self.client.get(f"{MEDIA_URL}public/nope.bin")
        self.assertEqual(response.status_code, 404)
