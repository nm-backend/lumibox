"""
Сигналы монетизации.

Пока нужен ровно один: правка партнёрского баннера в админке должна
появляться на витрине сразу, а не через время жизни кэша.

Подключаются в apps.py приложения billing.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.billing.models import Promotion
from apps.core.cache import invalidate_for_model


@receiver(post_save, sender=Promotion)
@receiver(post_delete, sender=Promotion)
def reset_cache_on_promotion_change(sender, instance, **kwargs):
    invalidate_for_model(sender._meta.label_lower)
