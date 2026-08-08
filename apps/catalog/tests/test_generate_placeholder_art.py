"""Тесты команды generate_placeholder_art.

Отдельный файл, потому что команда отвечает за обложки витрины, а не за
наполнение данными (то тестирует test_seed_command). Ключевой сценарий —
эфемерная файловая система (бесплатный Render): файл пропал при
перезапуске, но поле в БД осталось заполненным, и команда должна
перерисовать картинку, а не считать, что «постер уже есть».
"""

import os
from io import StringIO

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase

from apps.core.test_factories import create_title

POSTER_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


class GeneratePlaceholderArtTests(TestCase):
    def run_command(self, **options):
        output = StringIO()
        call_command("generate_placeholder_art", stdout=output, **options)
        return output.getvalue()

    def test_redraws_poster_when_file_disappeared(self):
        """Файл пропал (эфемерная ФС), поле в БД осталось — команда перерисует."""
        title = create_title()
        title.poster.save("poster.jpg", ContentFile(POSTER_BYTES), save=True)
        path = title.poster.path
        self.assertTrue(os.path.exists(path), "прекондиция: файл должен существовать")

        os.remove(path)
        self.assertFalse(os.path.exists(path))

        self.run_command()

        title.refresh_from_db()
        self.assertTrue(os.path.exists(title.poster.path), "команда должна перерисовать постер")

    def test_does_not_touch_existing_poster_file(self):
        """Постер на месте — команда не должна переписывать его и трогать поле."""
        title = create_title()
        title.poster.save("poster.jpg", ContentFile(POSTER_BYTES), save=True)
        original_name = title.poster.name
        path = title.poster.path

        self.run_command()

        title.refresh_from_db()
        self.assertEqual(title.poster.name, original_name, "поле не должно меняться")
        self.assertTrue(os.path.exists(path))

    def test_backdrop_redrawn_too(self):
        """Та же эфемерная проблема касается и фонов — перерисовываются оба."""
        title = create_title()
        title.backdrop.save("backdrop.jpg", ContentFile(POSTER_BYTES), save=True)
        os.remove(title.backdrop.path)

        self.run_command()

        title.refresh_from_db()
        self.assertTrue(os.path.exists(title.backdrop.path))
