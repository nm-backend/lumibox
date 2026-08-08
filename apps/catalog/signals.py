"""
Сигналы каталога — сбрасывают кэш при любом изменении контента.

Каждый post_save / post_delete / m2m_changed дергает единый оркестратор
apps.core.cache.invalidate_for_model, который знает, какие кэши зависят
от какой модели. Добавлять новые модели сюда проще, чем писать отдельный
обработчик для каждой.

Ограничение: сигналы не срабатывают на queryset.update() и
queryset.delete(). Массовые действия в админке сбрасывают кэш сами.
"""

from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from apps.catalog.models import (
    Award,
    Collection,
    CollectionItem,
    Country,
    Episode,
    Frame,
    Genre,
    Participation,
    Person,
    Studio,
    Title,
    TitleAward,
)
from apps.core.cache import invalidate_for_model

# ─── Базовый обработчик ────────────────────────────────────────────


def _invalidate(sender, instance, **kwargs):
    """Сбрасывает кэш для модели отправителя."""
    invalidate_for_model(sender._meta.label_lower)


# ─── Title — самый важный: публикация, обновление, удаление ─────────

@receiver(post_save, sender=Title)
@receiver(post_delete, sender=Title)
def reset_cache_on_title_change(sender, instance, **kwargs):
    _invalidate(sender, instance, **kwargs)


@receiver(m2m_changed, sender=Title.genres.through)
@receiver(m2m_changed, sender=Title.countries.through)
@receiver(m2m_changed, sender=Title.studios.through)
@receiver(m2m_changed, sender=Title.persons.through)
@receiver(m2m_changed, sender=Title.related_titles.through)
def reset_cache_on_title_m2m_change(sender, instance, action, **kwargs):
    """
    Сбрасывает кэш при изменении M2M-связей Title.

    post_save не срабатывает, когда редактор добавляет/убирает жанр
    у уже существующего фильма — M2M сохраняется отдельным запросом.
    Без этого обработчика фильтр по новому жанру не работал бы до TTL.

    related_titles включён отдельно: правка «Похожих вручную» должна
    сразу обновить страницу фильма, а не жить до истечения TTL кэша
    похожих (30 минут).
    """
    if action in ("post_add", "post_remove", "post_clear"):
        invalidate_for_model("catalog.title")


# ─── Подборки ───────────────────────────────────────────────────────

@receiver(post_save, sender=Collection)
@receiver(post_delete, sender=Collection)
@receiver(post_save, sender=CollectionItem)
@receiver(post_delete, sender=CollectionItem)
def reset_cache_on_collection_change(sender, instance, **kwargs):
    _invalidate(sender, instance, **kwargs)


# ─── Справочники ────────────────────────────────────────────────────

@receiver(post_save, sender=Genre)
@receiver(post_delete, sender=Genre)
@receiver(post_save, sender=Country)
@receiver(post_delete, sender=Country)
def reset_cache_on_reference_change(sender, instance, **kwargs):
    _invalidate(sender, instance, **kwargs)


# ─── Люди и участие ─────────────────────────────────────────────────

@receiver(post_save, sender=Person)
@receiver(post_delete, sender=Person)
@receiver(post_save, sender=Participation)
@receiver(post_delete, sender=Participation)
def reset_cache_on_person_change(sender, instance, **kwargs):
    _invalidate(sender, instance, **kwargs)


# ─── Медиа ──────────────────────────────────────────────────────────

@receiver(post_save, sender=Frame)
@receiver(post_delete, sender=Frame)
def reset_cache_on_frame_change(sender, instance, **kwargs):
    _invalidate(sender, instance, **kwargs)


# ─── Индустрия ──────────────────────────────────────────────────────

@receiver(post_save, sender=Studio)
@receiver(post_delete, sender=Studio)
@receiver(post_save, sender=Award)
@receiver(post_delete, sender=Award)
@receiver(post_save, sender=TitleAward)
@receiver(post_delete, sender=TitleAward)
def reset_cache_on_industry_change(sender, instance, **kwargs):
    _invalidate(sender, instance, **kwargs)


# ─── Удаление файлов из хранилища ───────────────────────────────────
# Django оставляет файлы на диске при удалении записи. На эфемерной ФС
# и в R2 это копит мусор, поэтому каждый post_delete чистит файлы полей
# модели (и WebP-копии) через apps.core.storage_cleanup.

@receiver(post_delete, sender=Title)
def delete_title_files(sender, instance, **kwargs):
    from apps.core.storage_cleanup import delete_media_files

    delete_media_files(instance, ["poster", "backdrop", "logo", "trailer_file"])


@receiver(post_delete, sender=Episode)
def delete_episode_file(sender, instance, **kwargs):
    from apps.core.storage_cleanup import delete_media_files

    delete_media_files(instance, ["file"])


@receiver(post_delete, sender=Frame)
def delete_frame_file(sender, instance, **kwargs):
    from apps.core.storage_cleanup import delete_media_files

    delete_media_files(instance, ["image"])


@receiver(post_delete, sender=Collection)
def delete_collection_cover(sender, instance, **kwargs):
    from apps.core.storage_cleanup import delete_media_files

    delete_media_files(instance, ["cover"])


@receiver(post_delete, sender=Studio)
def delete_studio_logo(sender, instance, **kwargs):
    from apps.core.storage_cleanup import delete_media_files

    delete_media_files(instance, ["logo"])


@receiver(post_delete, sender=Award)
def delete_award_logo(sender, instance, **kwargs):
    from apps.core.storage_cleanup import delete_media_files

    delete_media_files(instance, ["logo"])


@receiver(post_delete, sender=Person)
def delete_person_photo(sender, instance, **kwargs):
    from apps.core.storage_cleanup import delete_media_files

    delete_media_files(instance, ["photo"])
