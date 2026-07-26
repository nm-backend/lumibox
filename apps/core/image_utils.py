"""
Утилиты для оптимизации изображений.

Конвертирует загруженные изображения в WebP для ускорения загрузки.
WebP на 25-35% меньше JPEG при том же качестве.
"""

from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image


def convert_to_webp(image_field, quality=85):
    """Конвертирует ImageField в WebP и сохраняет.

    Args:
        image_field: Django ImageField instance
        quality: качество WebP (0-100), 85 — баланс размер/качество

    Returns:
        ContentFile с WebP данными или None если конвертация не удалась
    """
    try:
        img = Image.open(image_field)
        # Конвертируем в RGB если изображение в RGBA (для JPEG compatibility)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")

        buffer = BytesIO()
        img.save(buffer, format="WebP", quality=quality, method=6)
        return ContentFile(buffer.getvalue())
    except Exception:
        return None


def generate_thumbnail(image_field, size=(300, 450), quality=80):
    """Генерирует миниатюру изображения.

    Args:
        image_field: Django ImageField instance
        size: максимальные (width, height)
        quality: качество JPEG/WebP

    Returns:
        ContentFile с миниатюрой
    """
    try:
        img = Image.open(image_field)
        img.thumbnail(size, Image.Resampling.LANCZOS)

        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")

        buffer = BytesIO()
        img.save(buffer, format="WebP", quality=quality)
        return ContentFile(buffer.getvalue())
    except Exception:
        return None
