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

from django.conf import settings
from django.core.cache import cache

from apps.catalog.services import clear_home_cache, clear_reference_cache

logger = logging.getLogger(__name__)

# ─── Ключи кэша ─────────────────────────────────────────────────────
SIMILAR_CACHE_PREFIX = "catalog:similar:"
RECOMMENDATIONS_CACHE_PREFIX = "catalog:recommendations:"
YEAR_CHOICES_CACHE_KEY = "catalog:year_choices:v1"

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
    """Сбрасывает все кэши похожих фильмов (catalog:similar:*)."""
    if settings.REDIS_URL:
        try:
            cache.delete_pattern(f"{SIMILAR_CACHE_PREFIX}*")
            return
        except AttributeError:
            pass
    # LocMemCache: delete_pattern не работает — чистим всё.
    cache.clear()


def _clear_recommendations_cache():
    """Сбрасывает все персональные рекомендации."""
    if settings.REDIS_URL:
        try:
            cache.delete_pattern(f"{RECOMMENDATIONS_CACHE_PREFIX}*")
            return
        except AttributeError:
            pass
    # LocMemCache: delete_pattern не работает — чистим всё.
    cache.clear()


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

    _publish_invalidation(model_label)


def invalidate_all() -> None:
    """
    Полный сброс всех известных кэшей.

    Вместо cache.clear() (который снёс бы и чужие ключи, если Redis общий)
    сбрасываем только ключи, которые знает этот модуль.
    """
    for label, actions in CACHE_INVALIDATORS.items():
        for action in actions:
            try:
                action()
            except Exception:
                logger.exception("Cache invalidation failed for %s", label)
    _publish_invalidation("*")


# ─── Redis Pub/Sub ──────────────────────────────────────────────────


def _publish_invalidation(model_label: str) -> None:
    """
    Публикует событие инвалидации в Redis для других процессов.

    Без Redis — тихо проходим мимо. С Redis, но без установленного пакета
    redis — логируем предупреждение и продолжаем.
    """
    if not settings.REDIS_URL:
        return
    try:
        from redis import Redis

        r = Redis.from_url(settings.REDIS_URL)
        r.publish("lumibox:cache:invalidate", model_label)
    except ImportError:
        logger.warning("Redis package not installed — can't publish invalidation", exc_info=True)
    except Exception:
        logger.warning("Redis pub/sub publish failed", exc_info=True)
