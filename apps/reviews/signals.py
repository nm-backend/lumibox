"""
Сигналы отзывов.

Рейтинг фильма должен обновляться при любом изменении отзыва: из формы
на сайте, из админки, из будущего API или из shell. Ловить это в каждой
вьюхе значит однажды забыть в одной из них.

Важное ограничение: сигналы не срабатывают на queryset.update() и
queryset.delete(). Массовые действия в админке обновляют рейтинг сами,
а часовая задача refresh_title_ratings подчищает всё остальное.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.catalog.services import update_title_rating
from apps.core.cache import invalidate_for_model
from apps.reviews.models import Comment, Review


@receiver(post_save, sender=Review)
def update_rating_on_save(sender, instance, **kwargs):
    update_title_rating(instance.title)
    invalidate_for_model("reviews.review")


@receiver(post_delete, sender=Review)
def update_rating_on_delete(sender, instance, **kwargs):
    update_title_rating(instance.title)
    invalidate_for_model("reviews.review")


@receiver(post_save, sender=Comment)
@receiver(post_delete, sender=Comment)
def reset_cache_on_comment_change(sender, instance, **kwargs):
    """
    Рейтинг комментарий не трогает — сбрасываем только блок сайдбара
    «Последние комментарии», который кэшируется вместе с главной.
    """
    invalidate_for_model("reviews.comment")
