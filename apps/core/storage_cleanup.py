"""Очистка файлов из хранилища при удалении записей.

Django не удаляет файл из хранилища, когда удаляется модель с
FileField/ImageField, — освобождает только запись в базе. На эфемерной
файловой системе Render, а тем более в R2-бакете, это оставляет
осиротевшие файлы навсегда (и накапливает дубли при каждой замене).

Модуль подключается сигналами post_delete в apps.catalog.signals и
apps.users: удаляет файлы файловых полей модели, включая WebP-копии,
которые генерирует apps.catalog.webp.
"""

from __future__ import annotations

import logging
import os

from django.db.models.fields.files import FieldFile

logger = logging.getLogger("apps.core.storage_cleanup")


def _webp_name(name: str) -> str:
    """Путь WebP-копии, который строит apps.catalog.webp рядом с оригиналом."""
    base, _ = os.path.splitext(name)
    return f"{base}.webp"


def delete_field_file(field: FieldFile) -> None:
    """Удаляет один файл поля и его WebP-копию, если они существуют."""
    name = field.name
    if not name:
        return

    storage = field.storage
    try:
        if storage.exists(name):
            storage.delete(name)
            logger.debug("Deleted media file: %s", name)
    except NotImplementedError:
        # Хранилище без exists/delete — чистить нечего.
        return

    webp_name = _webp_name(name)
    try:
        if storage.exists(webp_name):
            storage.delete(webp_name)
            logger.debug("Deleted webp copy: %s", webp_name)
    except NotImplementedError:
        pass


def delete_media_files(instance, field_names: list[str]) -> None:
    """Удаляет перечисленные файловые поля модели. Вызывается из post_delete."""
    for field_name in field_names:
        field = getattr(instance, field_name, None)
        if isinstance(field, FieldFile):
            delete_field_file(field)
