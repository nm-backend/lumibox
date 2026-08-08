"""Сигналы приложения users: очистка файлов при удалении записей."""

from django.conf import settings
from django.db.models.signals import post_delete
from django.dispatch import receiver


@receiver(post_delete, sender=settings.AUTH_USER_MODEL)
def delete_user_avatar(sender, instance, **kwargs):
    from apps.core.storage_cleanup import delete_media_files

    delete_media_files(instance, ["avatar"])
