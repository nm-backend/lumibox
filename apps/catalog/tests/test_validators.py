"""Тесты валидаторов видеофайлов (сигнатура контейнера и лимит размера)."""

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.catalog.models import Episode, PlaybackSource
from apps.catalog.validators import (
    MAX_VIDEO_BYTES,
    validate_video_signature,
    validate_video_size,
)
from apps.core.test_factories import create_title


def mp4_bytes():
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2mp41"


class ValidateVideoSignatureTests(TestCase):
    def test_accepts_real_mp4(self):
        validate_video_signature(SimpleUploadedFile("a.mp4", mp4_bytes()))

    def test_accepts_real_webm(self):
        validate_video_signature(
            SimpleUploadedFile("a.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 16)
        )

    def test_accepts_real_ogg(self):
        validate_video_signature(SimpleUploadedFile("a.ogg", b"OggS" + b"\x00" * 16))

    def test_rejects_garbage_mp4(self):
        with self.assertRaises(ValidationError):
            validate_video_signature(SimpleUploadedFile("a.mp4", b"not-a-video"))

    def test_rejects_garbage_webm(self):
        with self.assertRaises(ValidationError):
            validate_video_signature(SimpleUploadedFile("a.webm", b"not-a-video"))

    def test_rejects_garbage_ogg(self):
        with self.assertRaises(ValidationError):
            validate_video_signature(SimpleUploadedFile("a.ogg", b"not-a-video"))

    def test_unknown_extension_skipped(self):
        validate_video_signature(SimpleUploadedFile("a.txt", b"anything"))


class ValidateVideoSizeTests(TestCase):
    def test_rejects_huge_file(self):
        big = SimpleUploadedFile("a.mp4", b"")
        big.size = MAX_VIDEO_BYTES + 1
        with self.assertRaises(ValidationError):
            validate_video_size(big)

    def test_accepts_normal_size(self):
        validate_video_size(SimpleUploadedFile("a.mp4", mp4_bytes()))


class PlaybackSourceFileValidationTests(TestCase):
    """
    Проверка подписи видео у источника.

    Раньше файл лежал в Episode.file и проверялся там же. Теперь у серии
    может быть несколько озвучек, поэтому и файл, и его валидаторы переехали
    в PlaybackSource — сюда же переехали и эти тесты.
    """

    def _source(self, payload):
        title = create_title()
        return PlaybackSource(
            title=title,
            episode=Episode.objects.create(title=title, season_number=1, episode_number=1),
            kind=PlaybackSource.Kind.FILE,
            file=SimpleUploadedFile("a.mp4", payload),
        )

    def test_full_clean_rejects_garbage_file(self):
        with self.assertRaises(ValidationError):
            self._source(b"garbage").full_clean()

    def test_full_clean_accepts_real_mp4(self):
        self._source(mp4_bytes()).full_clean()

    def test_embed_from_untrusted_host_rejected(self):
        """Внешний плеер обязан пройти белый список хостов."""
        source = PlaybackSource(
            title=create_title(),
            kind=PlaybackSource.Kind.EMBED,
            url="https://evil-youtube.com/embed/abc",
        )
        with self.assertRaises(ValidationError):
            source.full_clean()

    def test_embed_from_trusted_host_accepted(self):
        source = PlaybackSource(
            title=create_title(),
            kind=PlaybackSource.Kind.EMBED,
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )
        source.full_clean()

    def test_file_kind_requires_file(self):
        source = PlaybackSource(title=create_title(), kind=PlaybackSource.Kind.FILE)
        with self.assertRaises(ValidationError):
            source.full_clean()


class TrailerFileValidationTests(TestCase):
    def test_full_clean_rejects_garbage_file(self):
        title = create_title()
        title.trailer_file = SimpleUploadedFile("t.mp4", b"garbage")
        with self.assertRaises(ValidationError):
            title.full_clean()

    def test_full_clean_accepts_real_mp4(self):
        title = create_title()
        title.trailer_file = SimpleUploadedFile("t.mp4", mp4_bytes())
        title.full_clean()
