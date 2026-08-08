"""WebP-конвертация изображений при загрузке.

При сохранении Title, Frame, Collection (любая модель с ImageField)
генерирует WebP-копию загруженного изображения. Оригинал не удаляется —
CDN сам выбирает, что отдать браузеру по Accept-заголовку.

Пока конвертируются только новые файлы: если файл уже существовал
и не менялся, повторная конвертация не происходит.

Этот модуль подключается в apps.py приложения catalog через ready().
"""

from __future__ import annotations

import logging
import os

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger("apps.catalog.webp")

# Поля с изображениями, которые стоит конвертировать в WebP.
# Ключ — модель в формате app_label.ModelName, значение — список полей.
IMAGE_FIELDS_BY_MODEL: dict[str, list[str]] = {
    "catalog.Title": ["poster", "backdrop", "logo"],
    "catalog.Frame": ["image"],
    "catalog.Collection": ["cover"],
    "catalog.Person": ["photo"],
    "catalog.Studio": ["logo"],
    "catalog.Award": ["logo"],
    "users.User": ["avatar"],
}


def storage_is_local() -> bool:
    """Локальный ли дефолтный storage (FileSystemStorage).

    WebP-копии генерируются только для локального диска: у S3/R2 нет
    настоящего пути к файлу (field.path выбрасывает NotImplementedError),
    а сжатием на бакете занимается сам бакет или CDN.
    """
    from django.conf import settings

    backend = settings.STORAGES["default"]["BACKEND"]
    return backend.endswith("django.core.files.storage.FileSystemStorage")


def _get_webp_path(original_path: str) -> str:
    """Возвращает путь к WebP-файлу рядом с оригиналом."""
    base, _ = os.path.splitext(original_path)
    return f"{base}.webp"


def _convert_to_webp(image_path: str) -> str | None:
    """Конвертирует изображение в WebP, возвращает путь или None при ошибке."""
    from PIL import Image

    webp_path = _get_webp_path(image_path)

    # Если WebP уже существует и новее оригинала — пропускаем.
    if os.path.exists(webp_path) and os.path.getmtime(webp_path) >= os.path.getmtime(image_path):
        return webp_path

    try:
        img: Image.Image = Image.open(image_path)
        img = img.convert("RGBA") if img.mode in ("P",) else img
        img.save(
            webp_path,
            "WEBP",
            quality=85,
            method=6,  # Максимальное сжатие, медленнее но меньше размер
            lossless=False,
        )
        logger.debug("WebP created: %s", webp_path)
        return webp_path
    except Exception:
        logger.exception("Ошибка конвертации в WebP: %s", image_path)
        return None


@receiver(post_save)
def convert_images_to_webp(sender, instance, **kwargs) -> None:
    """Сигнал на post_save любой модели: конвертирует изображения в WebP.

    Срабатывает на все модели, но быстро выходит для тех, что не в списке.
    """
    model_key = f"{sender._meta.app_label}.{sender.__name__}"
    fields = IMAGE_FIELDS_BY_MODEL.get(model_key)
    if not fields:
        return

    # Если файловое хранилище не локальное (S3/R2), пропускаем —
    # конвертацию делает сам бакет или CDN.
    if not storage_is_local():
        return

    for field_name in fields:
        field = getattr(instance, field_name, None)
        if not field or not field.name:
            continue

        # Проверяем, что файл действительно изменился (не просто пересохранение).
        # У новой записи файл уже сохранён к моменту вызова post_save.
        try:
            image_path = field.path
            if os.path.exists(image_path):
                _convert_to_webp(image_path)
        except NotImplementedError:
            # Нелокальное хранилище (S3/R2) — path выбрасывает NotImplementedError.
            pass
        except Exception:
            logger.exception("WebP: ошибка при обработке %s.%s", model_key, field_name)
