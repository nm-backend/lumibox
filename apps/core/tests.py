import io

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image

from apps.core.validators import MAX_IMAGE_FILE_SIZE, validate_image_file


def make_png(width, height, name="test.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class ImageValidatorTests(TestCase):
    """
    Валидатор закрывает две дыры, которых не видит сам ImageField:
    вес файла и разрешение.
    """

    def test_normal_poster_passes(self):
        """Обычный постер не должен упираться в лимиты."""
        validate_image_file(make_png(600, 900))

    def test_oversized_file_rejected(self):
        """
        Без лимита веса авторизованный пользователь забивает диск
        одним запросом.
        """
        upload = make_png(10, 10)
        # Подменяем только размер: генерировать настоящие 6 МБ ради теста
        # незачем, проверяется именно граница.
        upload.size = MAX_IMAGE_FILE_SIZE + 1

        with self.assertRaises(ValidationError) as error:
            validate_image_file(upload)

        self.assertIn("слишком большой", str(error.exception).lower())

    def test_decompression_bomb_rejected(self):
        """
        Файл на сотни килобайт разворачивается в сотни мегабайт в памяти.
        По весу он проходит — ловить его можно только по разрешению.
        """
        bomb = make_png(9000, 9000, "bomb.png")
        self.assertLess(bomb.size, MAX_IMAGE_FILE_SIZE, "бомба должна проходить лимит веса")

        with self.assertRaises(ValidationError) as error:
            validate_image_file(bomb)

        self.assertIn("разрешение", str(error.exception).lower())

    def test_validator_runs_on_saved_field_too(self):
        """
        Валидатор навешен на модель, а туда файл приходит уже сохранённым,
        без атрибута .image. Прошлая версия из-за этого молча пропускала всё.
        """
        from apps.core.test_factories import create_title

        title = create_title()
        title.poster.save("bomb.png", make_png(9000, 9000), save=False)

        with self.assertRaises(ValidationError):
            title.full_clean(exclude=["slug"])

        title.poster.delete(save=False)
