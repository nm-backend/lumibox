"""
Сигналы стриминга — сбрасывают кэш при изменении сезонов, эпизодов
и видеоресурсов.

Подключаются в apps.py приложения streaming.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.core.cache import invalidate_for_model
from apps.streaming.models import Episode, Season, VideoAsset


@receiver(post_save, sender=Season)
@receiver(post_delete, sender=Season)
@receiver(post_save, sender=Episode)
@receiver(post_delete, sender=Episode)
@receiver(post_save, sender=VideoAsset)
@receiver(post_delete, sender=VideoAsset)
def reset_cache_on_streaming_change(sender, instance, **kwargs):
    """Новый сезон/серия/видео должны появиться на сайте сразу."""
    invalidate_for_model(sender._meta.label_lower)
