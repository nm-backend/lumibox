"""
Единый оркестратор инвалидации кэша.

Знает, какие модели какие кэши затрагивают — это единственное место,
где нужно добавить новую модель, чтобы её изменения начали сбрасывать
кэш. Сигналы дергают сюда, а не чистят кэш напрямую.

На больших проектах (Netflix, YouTube) инвалидация устроена так же:
одна кодовая база знает «какие данные зависят от какой модели».
Разница только в масштабе — там это сервис на Go, а у нас модуль на Python.
"""

from __future__ import annotations

import logging

from django.core.cache import cache

from apps.catalog.services import (
    RECOMMENDATIONS_GENERATION_KEY,
    SIMILAR_GENERATION_KEY,
    bump_generation,
    clear_home_cache,
    clear_reference_cache,
)

logger = logging.getLogger(__name__)

# ─── Действия инвалидации ───────────────────────────────────────────


def _clear_home_and_collections():
    """Главная + подборки: сбрасываем и кэш, и коллекции."""
    clear_home_cache()


def _clear_home_collections_similar():
    """Как выше + похожие фильмы (глобально через префикс)."""
    _clear_home_and_collections()
    _clear_similar_cache()


def _clear_all_title_caches():
    """Всё, что зависит от Title. Самая тяжёлая очистка."""
    clear_home_cache()
    _clear_similar_cache()
    _clear_recommendations_cache()


def _clear_reference_caches():
    """Жанры и страны."""
    clear_reference_cache()


def _clear_similar_cache():
    """
    Обесценивает все кэши похожих фильмов.

    Увеличиваем номер поколения вместо удаления ключей: перечислить их нечем.
    Здесь стоял cache.delete_pattern с откатом на cache.clear(), но
    delete_pattern есть только у пакета django-redis, а проект работает на
    штатном RedisCache Django — то есть откат срабатывал всегда, и правка
    одного фильма выносила весь кэш вместе с очередью Celery в том же Redis.
    """
    bump_generation(SIMILAR_GENERATION_KEY)


def _clear_recommendations_cache():
    """Обесценивает все персональные рекомендации — тем же инкрементом."""
    bump_generation(RECOMMENDATIONS_GENERATION_KEY)


def _clear_promotion_cache():
    """
    Партнёрские баннеры — по ключу на каждое размещение.

    Размещений всего три и они заданы в модели, поэтому ключи просто
    перечисляем: заводить ради них счётчик поколений незачем.
    """
    from apps.billing.models import Promotion
    from apps.billing.templatetags.promotions import PROMOTIONS_CACHE_KEY

    cache.delete_many([
        PROMOTIONS_CACHE_KEY.format(placement=placement)
        for placement in Promotion.Placement.values
    ])


def _clear_industry_cache():
    """Студии и награды — чистим страницы списков."""
    cache.delete_many([
        "catalog:studio_list:v1",
        "catalog:award_list:v1",
    ])
    _clear_home_and_collections()


# Маппинг модель → список действий инвалидации.
# ВАЖНО: ключи в нижнем регистре — соответствуют _meta.label_lower (а не _meta.label).
CACHE_INVALIDATORS: dict[str, list[callable]] = {
    # Главная страница
    "catalog.title": [_clear_all_title_caches],
    "catalog.collection": [_clear_home_and_collections],
    "catalog.collectionitem": [_clear_home_and_collections],
    # Справочники
    "catalog.genre": [_clear_reference_caches],
    "catalog.country": [_clear_reference_caches],
    # Люди и участие
    "catalog.person": [_clear_home_collections_similar],
    "catalog.participation": [_clear_home_collections_similar],
    # Медиа
    "catalog.frame": [_clear_home_collections_similar],
    # Индустрия
    "catalog.studio": [_clear_industry_cache],
    "catalog.award": [_clear_industry_cache],
    "catalog.titleaward": [_clear_home_collections_similar],
    # Стриминг
    "streaming.season": [_clear_home_collections_similar],
    "streaming.episode": [_clear_home_collections_similar],
    "streaming.videoasset": [_clear_home_collections_similar],
    # Отзывы
    "reviews.review": [_clear_all_title_caches],
    # Партнёрские баннеры
    "billing.promotion": [_clear_promotion_cache],
}


def invalidate_for_model(model_label: str) -> None:
    """
    Сбрасывает все кэши, которые зависят от указанной модели.

    Принимает: 'catalog.title', 'streaming.episode' и т.д. (lowercase).
    Ничего не делает, если модель не зарегистрирована в CACHE_INVALIDATORS.
    """
    actions = CACHE_INVALIDATORS.get(model_label.lower())
    if not actions:
        return

    for action in actions:
        try:
            action()
        except Exception:
            logger.exception("Cache invalidation failed for %s", model_label)


def invalidate_all() -> None:
    """
    Полный сброс всех известных кэшей.

    Зовётся руками из shell, когда нужно гарантированно показать всем
    свежие данные, не трогая чужие ключи в общем Redis.
    """
    for label, actions in CACHE_INVALIDATORS.items():
        for action in actions:
            try:
                action()
            except Exception:
                logger.exception("Cache invalidation failed for %s", label)
