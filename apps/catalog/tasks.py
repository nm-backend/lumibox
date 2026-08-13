"""
Фоновые задачи каталога.

Выполняются воркером Celery вне цикла запроса. Если Redis не настроен,
CELERY_TASK_ALWAYS_EAGER заставит их выполниться прямо на месте —
разработка от этого не встаёт.
"""

from decimal import Decimal

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Count, Q

from apps.catalog.models import Genre, Title
from apps.catalog.services import (
    REFERENCE_COUNTRY_CACHE_KEY,
    REFERENCE_GENRE_CACHE_KEY,
)


@shared_task
def sync_video_service():
    """
    Инкрементальная синхронизация ID каталога с видеосервисом.

    Вызывается планировщиком раз в сутки и подхватывает видео сервиса,
    добавленные или изменённые после прошлого запуска (отметка
    updated_from хранится в VideoServiceSyncState). Возвращает строку-отчёт —
    воркер логирует её, а ошибки API не роняют планировщик.

    Без ключа в настройках (VIDEO_SERVICE_API_KEY пуст) задача молча
    пропускается: каталог с пустым ключом синхронизировать нечем,
    а ежедневная ошибка в логах только зашумляла бы их.
    """
    from apps.catalog.video_service_api import VideoServiceAPIError
    from apps.catalog.video_service_sync import sync_video_service_ids

    if not (settings.VIDEO_SERVICE_API_KEY or "").strip():
        return "VIDEO_SERVICE_API_KEY не задан — синхронизация пропущена"

    try:
        stats = sync_video_service_ids()
    except VideoServiceAPIError as exc:
        return f"Ошибка синхронизации с видеосервисом: {exc}"

    return (
        f"Видеосервис: обработано {stats['fetched']}, совпадений "
        f"{stats['matched']}, заполнено kp_id {stats['kp_filled']}, "
        f"imdb_id {stats['imdb_filled']}, player_id {stats['player_filled']}"
    )


@shared_task
def sync_voiceovers():
    """
    Сопоставление озвучек каталога с озвучками видеосервиса.

    Вызывается планировщиком раз в сутки вслед за синхронизацией видео:
    проставляет vibix_voiceover_id озвучкам по названию, чтобы вкладка
    внешнего плеера могла передать data-voiceover. Тот же порядок, что
    у sync_video_service: без ключа — тихо пропускается, ошибки API
    не роняют планировщик.
    """
    from apps.catalog.video_service_api import VideoServiceAPIError
    from apps.catalog.video_service_voiceover_sync import sync_voiceover_ids

    if not (settings.VIDEO_SERVICE_API_KEY or "").strip():
        return "VIDEO_SERVICE_API_KEY не задан — синхронизация пропущена"

    try:
        stats = sync_voiceover_ids()
    except VideoServiceAPIError as exc:
        return f"Ошибка синхронизации озвучек: {exc}"

    return (
        f"Озвучки: получено {stats['fetched']}, "
        f"заполнено сопоставлений {stats['filled']}"
    )


@shared_task
def refresh_title_ratings():
    """
    Пересчитывает рейтинги всех записей разом.

    Страховка, а не основной путь: при обычной работе рейтинг обновляет
    update_title_rating сразу после изменения отзыва. Эта задача чинит
    расхождения после массовых действий в админке и прямых правок в базе.

    bulk_update вместо save() в цикле: тысяча записей — это один запрос,
    а не тысяча.
    """
    # Импорт внутри задачи: на уровне модуля приложения ещё не загружены.
    from apps.reviews.models import Review

    published = Q(reviews__status=Review.Status.PUBLISHED)

    titles = list(
        Title.objects.annotate(
            computed_average=Avg("reviews__rating", filter=published),
            computed_count=Count("reviews", filter=published),
        )
    )

    changed = []
    for title in titles:
        average = title.computed_average
        new_average = Decimal(average).quantize(Decimal("0.1")) if average is not None else None

        # Пишем только то, что реально изменилось: незачем гонять
        # в базу тысячи одинаковых значений.
        if title.rating_average != new_average or title.rating_count != title.computed_count:
            title.rating_average = new_average
            title.rating_count = title.computed_count
            changed.append(title)

    if changed:
        Title.objects.bulk_update(changed, ["rating_average", "rating_count"], batch_size=500)

    return f"Обновлено записей: {len(changed)} из {len(titles)}"


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
