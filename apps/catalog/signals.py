"""
Сигналы каталога.

Кэш главной страницы живёт пять минут. Без сброса только что
опубликованный фильм не появился бы на главной до истечения этого срока,
и редактор решил бы, что публикация не сработала.

Ограничение то же, что и у отзывов: сигналы не срабатывают на
queryset.update(). Массовые действия админки сбрасывают кэш сами.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.catalog.models import Collection, CollectionItem, Country, Genre, Title
from apps.catalog.services import clear_home_cache, clear_reference_cache


@receiver(post_save, sender=Title)
@receiver(post_delete, sender=Title)
@receiver(post_save, sender=Collection)
@receiver(post_delete, sender=Collection)
@receiver(post_save, sender=CollectionItem)
@receiver(post_delete, sender=CollectionItem)
def reset_home_cache(sender, instance, **kwargs):
    clear_home_cache()


@receiver(post_save, sender=Genre)
@receiver(post_delete, sender=Genre)
@receiver(post_save, sender=Country)
@receiver(post_delete, sender=Country)
def reset_reference_cache(sender, instance, **kwargs):
    """
    Сбрасывает кэш списков жанров и стран при их изменении.

    Новый жанр должен появиться на странице жанров сразу, а не через час.
    """
    clear_reference_cache()
