"""
Бизнес-логика каталога.

Здесь живут операции, которые нужны больше чем в одном месте:
их зовут вьюхи сайта, а скоро позовёт и REST API. Держать такие
функции во вьюхах значит переписать их второй раз для API.
"""

from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Count, F, Q

from apps.catalog.models import Collection, Country, Title
from apps.catalog.models.person import Participation

# Ключ кэша главной. Константа, а не строка по месту: сбрасывать кэш
# нужно из другого модуля, и опечатка там осталась бы незамеченной.
HOME_CACHE_KEY = "home:sections:v1"
HOME_SIDEBAR_CACHE_KEY = "home:sidebar:v1"


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


COLLECTIONS_CACHE_KEY = "catalog:featured_collections:v1"

# Похожие и рекомендации кэшируются по одному ключу на фильм и на человека,
# то есть ключей столько, сколько фильмов и пользователей. Перечислить их,
# чтобы удалить, нельзя: обычный Redis-бэкенд Django не умеет искать по маске.
#
# Поэтому в ключ подмешан номер поколения. Сбросить весь слой — значит увеличить
# номер на единицу: старые ключи мгновенно перестают совпадать и тихо истекают
# по своему TTL. Раньше на этом месте стоял cache.clear(), а он на Redis
# выполняет FLUSHDB — вычищает всю базу целиком, вместе с очередью Celery,
# которая живёт в том же Redis (CELERY_BROKER_URL = REDIS_URL).
SIMILAR_GENERATION_KEY = "catalog:similar:generation"
RECOMMENDATIONS_GENERATION_KEY = "catalog:recommendations:generation"

SIMILAR_CACHE_KEY = "catalog:similar:{generation}:{title_id}:v2"
RECOMMENDATIONS_CACHE_KEY = "catalog:recommendations:{generation}:{user_id}:v2"


def get_generation(generation_key):
    """Текущий номер поколения слоя кэша. Нет в кэше — начинаем с единицы."""
    generation = cache.get(generation_key)
    if generation is None:
        # timeout=None — «хранить без срока»: счётчик не должен истекать,
        # иначе номер откатится к единице и оживит старые ключи.
        cache.set(generation_key, 1, None)
        return 1
    return generation


def bump_generation(generation_key):
    """Обесценивает весь слой кэша одним инкрементом."""
    try:
        cache.incr(generation_key)
    except ValueError:
        # Счётчика ещё нет — тогда и обесценивать нечего, просто заводим его.
        cache.set(generation_key, 1, None)


def get_similar_titles(title, limit=6):
    """
    Похожие записи по числу совпавших жанров.

    Результат кэшируется на 30 минут: содержимое каталога
    меняется редко, а страница фильма — вторая по посещаемости.
    """
    key = SIMILAR_CACHE_KEY.format(
        generation=get_generation(SIMILAR_GENERATION_KEY), title_id=title.pk
    )
    cached = cache.get(key)
    if cached is not None:
        return cached

    manual = title.related_titles.published().with_related()[:limit]
    if manual:
        manual = list(manual)
        cache.set(key, manual, settings.CACHE_TTL_SIMILAR)
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
    cache.set(key, results, settings.CACHE_TTL_SIMILAR)
    return results


def get_recommendations(user, limit=12):
    """
    Персональные рекомендации по избранному пользователя.

    Кэшируются на 5 минут: избранное пользователя меняется нечасто.
    """
    popular = Title.objects.published().with_related().order_by(F("published_at").desc(nulls_last=True))

    if not user.is_authenticated:
        return list(popular[:limit])

    key = RECOMMENDATIONS_CACHE_KEY.format(
        generation=get_generation(RECOMMENDATIONS_GENERATION_KEY), user_id=user.pk
    )
    cached = cache.get(key)
    if cached is not None:
        return cached

    # order_by() снимает сортировку из Meta модели. Без него Django дописывает
    # release_year и name в SELECT DISTINCT, уникальность считается по тройке,
    # и один жанр возвращается столько раз, сколько у пользователя разных пар
    # «год + название». genres__isnull=False убирает NULL от левого соединения:
    # у фильма без жанров он давал список [None], который проходит проверку
    # ниже как непустой, но не находит ничего — вместо подборки пользователь
    # видел пустые рекомендации.
    favorite_genre_ids = list(
        Title.objects.filter(favorite__user=user, genres__isnull=False)
        .values_list("genres__id", flat=True)
        .order_by()
        .distinct()
    )
    if not favorite_genre_ids:
        results = list(popular[:limit])
        cache.set(key, results, settings.CACHE_TTL_RECOMMENDATIONS)
        return results

    seen_ids = list(Title.objects.filter(watchhistory__user=user).values_list("id", flat=True))
    favorite_ids = list(Title.objects.filter(favorite__user=user).values_list("id", flat=True))

    results = list(
        Title.objects.published()
        .with_related()
        .filter(genres__in=favorite_genre_ids)
        .exclude(pk__in=seen_ids + favorite_ids)
        .annotate(matched_genres=Count("genres", filter=Q(genres__in=favorite_genre_ids)))
        .order_by("-matched_genres", F("published_at").desc(nulls_last=True))[:limit]
    )
    cache.set(key, results, settings.CACHE_TTL_RECOMMENDATIONS)
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
    cache.set(COLLECTIONS_CACHE_KEY, results, settings.CACHE_TTL_HOME_LONG)
    return results[:limit]


def get_home_sidebar():
    """
    Данные сайдбара главной: страны, обновления сериалов,
    последние отзывы.

    Кэшируются одним куском вместе с get_home_sections: меняются редко,
    а отдельными запросами на каждый заход стоили бы четыре запроса.
    """
    from apps.reviews.models import Review

    cached = cache.get(HOME_SIDEBAR_CACHE_KEY)
    if cached is not None:
        return cached

    published = Title.objects.published()
    sidebar = {
        "countries": list(
            Country.objects.annotate(
                titles_count=Count("titles", filter=Q(titles__status=Title.Status.PUBLISHED))
            )
            .filter(titles_count__gt=0)
            .order_by("name")
        ),
        "series_updates": list(
            published.series().with_related().order_by(F("published_at").desc(nulls_last=True))[:6]
        ),
        "latest_reviews": list(
            Review.objects.filter(status=Review.Status.PUBLISHED)
            .select_related("user", "title")
            .order_by("-created_at")[:4]
        ),
        # Топ популярного за всё время — для блока «Популярное» сайдбара.
        # Кэш живёт столько же, сколько и остальной сайдбар: счётчик
        # просмотров растёт часто, но сайдбар обновляется раз в CACHE_TTL_HOME.
        # Только реально просмотренное (views_count > 0): иначе блок вырождается
        # в «последние добавленные» и чужие тайтлы мелькают в сайдбаре.
        "most_viewed": list(published.filter(views_count__gt=0).most_viewed(limit=5)),
    }
    cache.set(HOME_SIDEBAR_CACHE_KEY, sidebar, settings.CACHE_TTL_HOME)
    return sidebar


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

    # Раньше здесь на каждую секцию шёл свой запрос СО ВСЕМИ prefetch:
    # шесть секций тянули жанры, страны, студии и участия по шесть раз,
    # и главная на холодном кэше делала около шестидесяти запросов.
    #
    # Теперь в два шага. Сначала шесть дешёвых запросов решают, ЧТО войдёт
    # в каждую секцию и в каком порядке. Затем один запрос со связями
    # поднимает объединение — секции пересекаются, и один и тот же фильм
    # больше не грузится несколько раз.
    base = Title.objects.published()

    raw = {
        # list() обязателен: QuerySet ленивый, в кэш попал бы объект запроса,
        # и каждый читатель кэша ходил бы в базу заново.
        "featured": list(base.exclude(description="").order_by(F("published_at").desc(nulls_last=True))[:1]),
        # Герои для авто-ротации: топ-6 по рейтингу с описанием
        "hero_titles": list(base.exclude(description="").order_by(F("rating_average").desc(nulls_last=True))[:6]),
        "new_titles": list(base.order_by(F("published_at").desc(nulls_last=True))[:12]),
        "movies": list(base.movies()[:6]),
        "series": list(base.series()[:6]),
        "top_rated": list(base.top_rated()[:6]),
    }

    identifiers = {item.pk for group in raw.values() for item in group}
    loaded = {
        item.pk: item
        for item in Title.objects.filter(pk__in=identifiers).with_related().with_crew()
    }

    # Порядок берём из первого шага: filter(pk__in=...) его не сохраняет.
    sections = {
        name: [loaded[item.pk] for item in group if item.pk in loaded]
        for name, group in raw.items()
    }
    # Баннер — одна запись, а не список: шаблон ждёт объект.
    sections["featured"] = sections["featured"][0] if sections["featured"] else None

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
    from apps.catalog.views import GENRE_CHIPS_CACHE_KEY

    cache.delete_many([
        HOME_CACHE_KEY,
        HOME_SIDEBAR_CACHE_KEY,
        HOME_TRENDING_CACHE_KEY,
        HOME_STATS_CACHE_KEY,
        YEAR_CHOICES_CACHE_KEY,
        COLLECTIONS_CACHE_KEY,
        GENRE_CHIPS_CACHE_KEY,
    ])


def get_home_statistics():
    """Счётчики для главной: фильмы, сериалы, пользователи, отзывы."""
    from django.contrib.auth import get_user_model

    from apps.reviews.models import Review

    cached = cache.get(HOME_STATS_CACHE_KEY)
    if cached is not None:
        return cached
    stats = {
        "movies_count": Title.objects.published().movies().count(),
        "series_count": Title.objects.published().series().count(),
        "published_count": Title.objects.published().count(),
        "users_count": get_user_model().objects.count(),
        "reviews_count": Review.objects.count(),
    }
    cache.set(HOME_STATS_CACHE_KEY, stats, settings.CACHE_TTL_HOME)
    return stats


HOME_STATS_CACHE_KEY = "home:statistics:v1"


def get_trending_titles():
    """Популярное за неделю (по просмотрам)."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.library.models import WatchHistory

    cached = cache.get(HOME_TRENDING_CACHE_KEY)
    if cached is not None:
        return cached
    week_ago = timezone.now() - timedelta(days=7)
    trending_ids = (
        WatchHistory.objects
        .filter(watched_at__gte=week_ago, title__status=Title.Status.PUBLISHED)
        .values("title_id")
        .annotate(views=Count("id"))
        .order_by("-views")[:12]
    )
    ids = [t["title_id"] for t in trending_ids]
    if ids:
        titles = list(Title.objects.published().with_related().with_crew().filter(id__in=ids))
        titles.sort(key=lambda t: ids.index(t.id))
    else:
        titles = list(Title.objects.published().with_related().with_crew()
                  .order_by(F("rating_average").desc(nulls_last=True))[:6])
    cache.set(HOME_TRENDING_CACHE_KEY, titles, settings.CACHE_TTL_HOME)
    return titles


HOME_TRENDING_CACHE_KEY = "home:trending:v1"


def clear_reference_cache():
    """
    Сбрасывает кэш списков жанров и стран.

    Зовётся при добавлении/удалении Genre или Country: новый жанр должен
    появиться в списке на сайте сразу, а не через час.

    Чипсы навигации (GENRE_CHIPS_CACHE_KEY) сбрасываем здесь же: они
    кэшируются отдельным ключом в catalog/views.py и без этого оставались
    бы устаревшими до истечения TTL (1 час).
    """
    from apps.catalog.views import GENRE_CHIPS_CACHE_KEY

    cache.delete_many([
        REFERENCE_GENRE_CACHE_KEY,
        REFERENCE_COUNTRY_CACHE_KEY,
        GENRE_CHIPS_CACHE_KEY,
    ])
