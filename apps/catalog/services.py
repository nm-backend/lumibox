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


DEFAULT_HOME_CACHE_TTL = 60 * 5  # 5 minutes
SIMILAR_CACHE_KEY = "catalog:similar:{title_id}:v1"
RECOMMENDATIONS_CACHE_KEY = "catalog:recommendations:{user_id}:v1"
COLLECTIONS_CACHE_KEY = "catalog:featured_collections:v1"


def get_similar_titles(title, limit=6):
    """
    Похожие записи по числу совпавших жанров.

    Результат кэшируется на 30 минут: содержимое каталога
    меняется редко, а страница фильма — вторая по посещаемости.
    """
    key = SIMILAR_CACHE_KEY.format(title_id=title.pk)
    cached = cache.get(key)
    if cached is not None:
        return cached

    manual = title.related_titles.published().with_related()[:limit]
    if manual:
        manual = list(manual)
        cache.set(key, manual, 60 * 30)
        return manual

    genre_ids = list(title.genres.values_list("id", flat=True))
    if not genre_ids:
        return Title.objects.none()

    results = list(
        Title.objects.published()
        .with_related()
        .filter(genres__in=genre_ids)
        .exclude(pk=title.pk)
        .annotate(shared_genres=Count("genres", filter=Q(genres__in=genre_ids)))
        .order_by("-shared_genres", "-release_year")[:limit]
    )
    cache.set(key, results, 60 * 30)
    return results


def get_recommendations(user, limit=12):
    """
    Персональные рекомендации по избранному пользователя.

    Кэшируются на 5 минут: избранное пользователя меняется нечасто.
    """
    popular = Title.objects.published().with_related().order_by("-published_at")

    if not user.is_authenticated:
        return list(popular[:limit])

    key = RECOMMENDATIONS_CACHE_KEY.format(user_id=user.pk)
    cached = cache.get(key)
    if cached is not None:
        return cached

    favorite_genre_ids = list(
        Title.objects.filter(favorite__user=user).values_list("genres__id", flat=True).distinct()
    )
    if not favorite_genre_ids:
        results = list(popular[:limit])
        cache.set(key, results, 60 * 5)
        return results

    seen_ids = list(Title.objects.filter(watchhistory__user=user).values_list("id", flat=True))
    favorite_ids = list(Title.objects.filter(favorite__user=user).values_list("id", flat=True))

    results = list(
        Title.objects.published()
        .with_related()
        .filter(genres__in=favorite_genre_ids)
        .exclude(pk__in=seen_ids + favorite_ids)
        .annotate(matched_genres=Count("genres", filter=Q(genres__in=favorite_genre_ids)))
        .order_by("-matched_genres", "-published_at")[:limit]
    )
    cache.set(key, results, 60 * 5)
    return results


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
    """Подборки для главной страницы. Кэшируются на 10 минут."""
    cached = cache.get(COLLECTIONS_CACHE_KEY)
    if cached is not None:
        return cached[:limit] if len(cached) > limit else cached

    results = list(
        Collection.objects.featured()
        .annotate(titles_count=Count("titles", filter=Q(titles__status=Title.Status.PUBLISHED)))
        .filter(titles_count__gt=0)
        .order_by("order", "-created_at")
    )
    cache.set(COLLECTIONS_CACHE_KEY, results, 60 * 10)
    return results[:limit]


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
        # list() обязателен: QuerySet ленивый, в кэш попал бы не результат,
        # а объект запроса, и каждый читатель кэша ходил бы в базу заново.
        "featured": published.exclude(description="").order_by("-published_at").first(),
        # Герои для авто-ротации: топ-6 по рейтингу с описанием
        "hero_titles": list(
            published.exclude(description="")
            .order_by("-rating_average")[:6]
        ),
        "new_titles": list(published.order_by("-published_at")[:12]),
        "movies": list(published.movies()[:6]),
        "series": list(published.series()[:6]),
        "top_rated": list(published.top_rated()[:6]),
    }

    cache.set(HOME_CACHE_KEY, sections, settings.CACHE_TTL_HOME)
    return sections


# Ключи кэша справочников — вынесены в константы для использования в signals.py
REFERENCE_GENRE_CACHE_KEY = "catalog:genre_list:v1"
REFERENCE_COUNTRY_CACHE_KEY = "catalog:country_list:v1"


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

    cache.delete_many([
        HOME_CACHE_KEY,
        YEAR_CHOICES_CACHE_KEY,
        COLLECTIONS_CACHE_KEY,
    ])


def clear_reference_cache():
    """
    Сбрасывает кэш списков жанров и стран.

    Зовётся при добавлении/удалении Genre или Country: новый жанр должен
    появиться в списке на сайте сразу, а не через час.
    """
    cache.delete_many([REFERENCE_GENRE_CACHE_KEY, REFERENCE_COUNTRY_CACHE_KEY])
