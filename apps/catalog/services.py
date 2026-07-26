"""
Бизнес-логика каталога.

Здесь живут операции, которые нужны больше чем в одном месте:
их зовут вьюхи сайта, а скоро позовёт и REST API. Держать такие
функции во вьюхах значит переписать их второй раз для API.
"""

from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Count, Q

from apps.catalog.models import Collection, Title
from apps.catalog.models.person import Participation

# Ключ кэша главной. Константа, а не строка по месту: сбрасывать кэш
# нужно из другого модуля, и опечатка там осталась бы незамеченной.
HOME_CACHE_KEY = "home:sections:v1"


def update_title_rating(title):
    """
    Пересчитывает рейтинг одной записи.

    Вызывается сразу после изменения отзыва: пользователь должен увидеть
    свою оценку немедленно, а не через час, когда отработает задача.
    Один агрегирующий запрос — это дёшево.

    filter внутри Avg обязателен: скрытые модерацией отзывы
    не должны влиять на рейтинг.
    """
    from apps.reviews.models import Review

    stats = Review.objects.filter(
        title=title,
        status=Review.Status.PUBLISHED,
    ).aggregate(average=Avg("rating"), count=Count("id"))

    average = stats["average"]

    # update() вместо save(): не трогаем updated_at и не запускаем
    # логику save() — рейтинг это служебное поле, а не правка редактора.
    Title.objects.filter(pk=title.pk).update(
        rating_average=Decimal(average).quantize(Decimal("0.1")) if average is not None else None,
        rating_count=stats["count"],
    )


def get_similar_titles(title, limit=6):
    """
    Похожие записи по числу совпавших жанров.

    Если редактор задал похожие вручную — берём его выбор: человек знает
    о связях, которых в жанрах не видно (продолжение, тот же режиссёр).
    Если не задал, работает эвристика: сортируем по количеству общих
    жанров, при равенстве — по свежести.
    """
    manual = title.related_titles.published().with_related()[:limit]
    if manual:
        return manual

    genre_ids = list(title.genres.values_list("id", flat=True))
    if not genre_ids:
        return Title.objects.none()

    return (
        Title.objects.published()
        .with_related()
        .filter(genres__in=genre_ids)
        .exclude(pk=title.pk)
        .annotate(shared_genres=Count("genres", filter=Q(genres__in=genre_ids)))
        .order_by("-shared_genres", "-release_year")[:limit]
    )


def get_recommendations(user, limit=12):
    """
    Персональные рекомендации.

    Стратегия:
    1. По жанрам из избранного + рейтинг (для пользователей с избранным)
    2. Trending: популярное по просмотрам (для гостей и новичков)
    3. Fallback: свежее (если нет данных о просмотрах)
    """
    if not user.is_authenticated:
        return _get_trending_or_popular(limit)

    favorite_genre_ids = list(
        Title.objects.filter(favorite__user=user).values_list("genres__id", flat=True).distinct()
    )
    if not favorite_genre_ids:
        return _get_trending_or_popular(limit)

    seen_ids = list(Title.objects.filter(watchhistory__user=user).values_list("id", flat=True))
    favorite_ids = list(Title.objects.filter(favorite__user=user).values_list("id", flat=True))
    exclude_ids = seen_ids + favorite_ids

    # Рекомендации строго по жанрам из избранного
    genre_based = (
        Title.objects.published()
        .with_related()
        .filter(genres__in=favorite_genre_ids)
        .exclude(pk__in=exclude_ids)
        .annotate(matched_genres=Count("genres", filter=Q(genres__in=favorite_genre_ids)))
        .order_by("-matched_genres", "-rating_average")
    )

    results = list(genre_based[:limit])

    # Если жанровых результатов нет вообще — добираем trending
    if not results:
        return _get_trending_or_popular(limit, exclude_ids=exclude_ids)

    return results


def _get_trending_or_popular(limit, exclude_ids=None):
    """Trending по просмотрам, fallback — популярное по дате."""
    qs = Title.objects.published().with_related()
    if exclude_ids:
        qs = qs.exclude(pk__in=exclude_ids)

    trending = list(qs.filter(view_count__gt=0).order_by("-view_count", "-rating_average")[:limit])
    if trending:
        return trending
    return list(qs.order_by("-published_at")[:limit])


def get_trending_weekly(limit=12):
    """Популярное за последнюю неделю (по WatchProgress)."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.streaming.models import WatchProgress

    week_ago = timezone.now() - timedelta(days=7)

    # Получаем id самых просматриваемых titles за неделю
    trending_ids = (
        WatchProgress.objects.filter(last_watched_at__gte=week_ago)
        .values("video_asset__title")
        .annotate(watch_count=Count("id"))
        .order_by("-watch_count")
        .values_list("video_asset__title", flat=True)[:limit]
    )

    if not trending_ids:
        return Title.objects.published().with_related().order_by("-published_at")[:limit]

    # Сохраняем порядок из annotate
    titles = list(Title.objects.published().with_related().filter(pk__in=trending_ids))
    id_order = {pk: i for i, pk in enumerate(trending_ids)}
    titles.sort(key=lambda t: id_order.get(t.pk, 999))
    return titles


def get_crew_by_role(title):
    """
    Съёмочная группа, разложенная по ролям.

    Возвращает список пар (подпись роли, список участий), чтобы шаблон
    не делал по запросу на каждую роль. Данные берём из уже загруженного
    prefetch — новых обращений к базе здесь нет.
    """
    grouped = {}

    for participation in title.participations.all():
        grouped.setdefault(participation.role, []).append(participation)

    role_labels = dict(Participation.Role.choices)

    # Порядок ролей берём из модели: режиссёр должен идти перед актёрами,
    # а не как получится из словаря.
    return [
        (role_labels[role], grouped[role])
        for role, _ in Participation.Role.choices
        if role in grouped
    ]


def get_featured_collections(limit=4):
    """Подборки для главной страницы."""
    # order_by после annotate — не дублирование Meta.ordering: GROUP BY
    # сбрасывает сортировку модели, и срез [:limit] отдавал бы четыре
    # случайные подборки вместо тех, что редактор поставил первыми.
    return (
        Collection.objects.featured()
        .annotate(titles_count=Count("titles", filter=Q(titles__status=Title.Status.PUBLISHED)))
        .filter(titles_count__gt=0)
        .order_by("order", "-created_at")[:limit]
    )


def get_home_sections():
    """
    Подборки главной страницы одним куском, с кэшем.

    Главная — самая посещаемая страница, а её содержимое меняется редко:
    новый фильм появляется не каждую секунду. Держим результат в кэше
    и экономим пять запросов на каждом заходе гостя.

    Кэш общий для всех неавторизованных: персонального здесь ничего нет,
    личные рекомендации собираются отдельно и не кэшируются.
    """
    cached = cache.get(HOME_CACHE_KEY)
    if cached is not None:
        return cached

    published = Title.objects.published().with_related()

    sections = {
        "featured": published.exclude(description="").order_by("-published_at").first(),
        "new_titles": list(published.order_by("-published_at")[:12]),
        "movies": list(published.movies()[:6]),
        "series": list(published.series()[:6]),
        "top_rated": list(published.top_rated()[:6]),
        "trending": list(
            published.filter(view_count__gt=0).order_by("-view_count")[:6]
        ),
        "trending_weekly": list(get_trending_weekly(6)),
    }

    cache.set(HOME_CACHE_KEY, sections, settings.CACHE_TTL_HOME)
    return sections


def clear_home_cache():
    """
    Сбрасывает кэши, зависящие от состава каталога.

    Зовётся при публикации записи. Список годов для фильтра сбрасываем
    здесь же: новый фильм 2026 года должен появиться в выпадающем списке
    сразу, а не через пять минут.
    """
    # Импорт внутри функции: forms импортирует models, а services —
    # forms, и на уровне модуля это замкнулось бы в круг.
    from apps.catalog.forms import YEAR_CHOICES_CACHE_KEY

    cache.delete_many([HOME_CACHE_KEY, YEAR_CHOICES_CACHE_KEY])
