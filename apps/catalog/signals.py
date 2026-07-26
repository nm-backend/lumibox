"""
Сигналы каталога.

Кэш главной страницы живёт пять минут. Без сброса только что
опубликованный фильм не появился бы на главной до истечения этого срока,
и редактор решил бы, что публикация не сработала.

При публикации/обновлении фильма — broadcast через WebSocket,
чтобы все подключённые пользователи увидели изменения сразу.

Ограничение: сигналы не срабатывают на queryset.update().
Массовые действия админки сбрасывают кэш сами.
"""

import logging

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from apps.catalog.models import Collection, CollectionItem, Title
from apps.catalog.services import clear_home_cache

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Title)
@receiver(post_delete, sender=Title)
@receiver(post_save, sender=Collection)
@receiver(post_delete, sender=Collection)
@receiver(post_save, sender=CollectionItem)
@receiver(post_delete, sender=CollectionItem)
def reset_home_cache(sender, instance, **kwargs):
    """Сбрасывает кэш главной при любом изменении каталога."""
    clear_home_cache()


@receiver(pre_save, sender=Title)
def convert_images_to_webp(sender, instance, **kwargs):
    """Конвертирует постер и бэкдроп в WebP при сохранении."""
    from apps.core.image_utils import convert_to_webp

    for field_name in ("poster", "backdrop"):
        field = getattr(instance, field_name)
        if not field or not hasattr(field, "file"):
            continue

        # Конвертируем только если файл изменился
        try:
            field.file.seek(0)
            webp = convert_to_webp(field.file)
            if webp:
                webp.name = f"{field.name.rsplit('.', 1)[0]}.webp"
                setattr(instance, field_name, webp)
        except Exception:
            pass  # Оставляем оригинальный файл


@receiver(post_save, sender=Title)
def broadcast_title_change(sender, instance, created, **kwargs):
    """
    При сохранении Title — broadcast через WebSocket.

    Если фильм опубликован — все пользователи получают уведомление
    с предложением обновить страницу.
    """
    if instance.status != Title.Status.PUBLISHED:
        return

    try:
        from apps.core.notifications import notify_content_published, notify_content_updated

        if created:
            notify_content_published(instance)
        else:
            notify_content_updated(instance)
    except Exception:
        logger.debug("WebSocket broadcast failed")


@receiver(post_delete, sender=Title)
def broadcast_title_delete(sender, instance, **kwargs):
    """При удалении Title — broadcast через WebSocket."""
    try:
        from apps.core.notifications import notify_content_deleted

        notify_content_deleted(instance.name)
    except Exception:
        logger.debug("WebSocket broadcast failed")
