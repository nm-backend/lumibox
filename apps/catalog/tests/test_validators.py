"""Тесты валидаторов видеофайлов (сигнатура контейнера и лимит размера)."""

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.catalog.models import Episode
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


class EpisodeFileValidationTests(TestCase):
    def test_full_clean_rejects_garbage_file(self):
        episode = Episode(
            title=create_title(),
            season_number=1,
            episode_number=1,
            file=SimpleUploadedFile("a.mp4", b"garbage"),
        )
        with self.assertRaises(ValidationError):
            episode.full_clean()

    def test_full_clean_accepts_real_mp4(self):
        episode = Episode(
            title=create_title(),
            season_number=1,
            episode_number=1,
            file=SimpleUploadedFile("a.mp4", mp4_bytes()),
        )
        episode.full_clean()


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
