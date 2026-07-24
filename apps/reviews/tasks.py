"""Celery tasks: cache warming for high-traffic pages."""

from celery import shared_task
from django.db.models import Count, Q


@shared_task
def warm_home_cache():
    """Pre-warm the home page cache so the first visitor doesn't wait.

    Runs every 2 minutes via Celery Beat. Falls back to synchronous
    execution if no Celery worker (task_always_eager=True).
    """
    from apps.catalog.services import get_home_sections

    get_home_sections()
    return "Home cache warmed"


@shared_task
def warm_reference_caches():
    """Pre-warm genre and country list caches.

    Runs every 30 minutes. Keeps reference data fresh without
    waiting for a user request to trigger cache population.
    """
    from django.conf import settings
    from django.core.cache import cache

    from apps.catalog.models import Genre, Title
    from apps.catalog.services import REFERENCE_COUNTRY_CACHE_KEY, REFERENCE_GENRE_CACHE_KEY

    published_titles = Q(titles__status=Title.Status.PUBLISHED)

    genres = list(
        Genre.objects.annotate(
            titles_count=Count("titles", filter=published_titles),
        )
        .filter(titles_count__gt=0)
        .order_by("name")
    )
    cache.set(REFERENCE_GENRE_CACHE_KEY, genres, settings.CACHE_TTL_REFERENCE)

    from apps.catalog.models import Country

    countries = list(
        Country.objects.annotate(
            titles_count=Count("titles", filter=published_titles),
        )
        .filter(titles_count__gt=0)
        .order_by("name")
    )
    cache.set(REFERENCE_COUNTRY_CACHE_KEY, countries, settings.CACHE_TTL_REFERENCE)

    return f"Cached {len(genres)} genres and {len(countries)} countries"
