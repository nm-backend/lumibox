"""
Валидаторы изображений.

ImageField сам по себе проверяет только одно: что файл вообще является
картинкой (это делает Pillow, и делает хорошо — подделать расширение
или подсунуть SVG со скриптом через него не выйдет).

Чего ImageField НЕ проверяет: сколько картинка весит и какого она размера.
Django тоже не помогает: DATA_UPLOAD_MAX_MEMORY_SIZE на файловые поля
не распространяется, а FILE_UPLOAD_MAX_MEMORY_SIZE лишь решает, держать
файл в памяти или писать во временный, — верхней границы у него нет.
"""

from django.core.exceptions import ValidationError
from django.core.files.images import get_image_dimensions

# 5 МБ хватает постеру в хорошем качестве. Без лимита авторизованный
# пользователь заливает файл любого размера и забивает диск.
MAX_IMAGE_FILE_SIZE = 5 * 1024 * 1024

# 50 мегапикселей — с запасом для любого постера (это примерно 7000x7000).
# Ограничение против «декомпрессионной бомбы»: файл на 400 КБ разворачивается
# в сотни мегабайт в памяти у того, кто возьмётся его обрабатывать.
MAX_IMAGE_PIXELS = 50_000_000


def validate_image_file(image):
    """
    Проверяет вес и размер загружаемой картинки.

    Принимает: файл из ImageField.
    Ничего не возвращает; при нарушении поднимает ValidationError,
    и форма показывает ошибку рядом с полем.
    """
    if image.size > MAX_IMAGE_FILE_SIZE:
        raise ValidationError(
            "Файл слишком большой: %(actual)s МБ. Максимум — %(limit)s МБ.",
            params={
                "actual": round(image.size / 1024 / 1024, 1),
                "limit": MAX_IMAGE_FILE_SIZE // 1024 // 1024,
            },
        )

    width, height = _get_dimensions(image)
    if width * height > MAX_IMAGE_PIXELS:
        raise ValidationError(
            "Слишком большое разрешение: %(width)sx%(height)s. Максимум — %(limit)s мегапикселей.",
            params={
                "width": width,
                "height": height,
                "limit": MAX_IMAGE_PIXELS // 1_000_000,
            },
        )


def _get_dimensions(image):
    """
    Возвращает (ширина, высота) картинки.

    get_image_dimensions читает только заголовок файла и не разворачивает
    пиксели в память — именно поэтому им можно измерять бомбу, не подрываясь
    на ней. Работает и со свежей загрузкой, и с уже сохранённым полем.

    Раньше здесь стоял getattr(image, "image", None) с возвратом None.
    Атрибут image есть только у свежей загрузки после ImageField.to_python,
    а валидатор модели получает файл уже сохранённым — проверка молча
    не срабатывала ни разу.
    """
    return get_image_dimensions(image)
