import time

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils.translation import gettext as _


def global_settings(request):
    return {
        "ga_measurement_id": getattr(settings, "GA_MEASUREMENT_ID", ""),
    }


def static_version(request):
    return {
        "static_version": int(time.time()),
    }


def kg_topnav(request):
    """Верхняя навигация в стиле Kinogo — одинаковая на всех страницах."""
    from apps.catalog.models import Genre, Title

    catalog_url = reverse("catalog:title_list")
    url_name = getattr(request.resolver_match, "url_name", "")
    get = request.GET
    links = [
        (_("Главная"), reverse("catalog:home"), url_name == "home"),
        (_("Новинки"), f"{catalog_url}?sort=-published_at", get.get("sort") == "-published_at"),
        (_("Подборки"), reverse("catalog:collection_list"),
         url_name in ("collection_list", "collection_detail")),
        (_("Фильмы"), f"{catalog_url}?type={Title.Type.MOVIE}", get.get("type") == str(Title.Type.MOVIE)),
        (_("Сериалы"), f"{catalog_url}?type={Title.Type.SERIES}", get.get("type") == str(Title.Type.SERIES)),
    ]
    has_anime = cache.get("kg_topnav_has_anime")
    if has_anime is None:
        has_anime = Genre.objects.filter(slug="animaciya").exists()
        cache.set("kg_topnav_has_anime", has_anime, 60 * 60)
    if has_anime:
        slug = ""
        if request.resolver_match:
            slug = request.resolver_match.kwargs.get("slug", "")
        links.append((_("Аниме"), reverse("catalog:genre_titles", args=["animaciya"]),
                      url_name == "genre_titles" and slug == "animaciya"))
    return {"kg_topnav": links}


def kg_sidebar(request):
    """Боковая панель внутренних страниц: популярное, новинки, жанры.

    Данные общие для всех страниц и кэшируются на 5 минут.
    Вьюхи каталога могут переопределить эти ключи — контекст вьюхи
    имеет приоритет над контекст-процессором.
    """
    from apps.catalog.models import Genre, Title

    data = cache.get("kg_sidebar_data")
    if data is None:
        published = Title.objects.published()
        data = {
            "sidebar_popular": list(published.order_by("-rating_average")[:6]),
            "sidebar_new": list(published.order_by("-published_at", "-id")[:6]),
            "sidebar_genres": list(Genre.objects.all()[:24]),
        }
        cache.set("kg_sidebar_data", data, 5 * 60)
    return data
