import os
from functools import lru_cache

from django.conf import settings
from django.urls import reverse
from django.utils.functional import SimpleLazyObject
from django.utils.translation import gettext as _


def global_settings(request):
    return {
        "ga_measurement_id": getattr(settings, "GA_MEASUREMENT_ID", ""),
    }


def static_version(request):
    """
    Стабильный номер версии статики для cache-busting (?v=...).

    В разработке считаем на каждый запрос: правка CSS/JS должна быть видна
    сразу, без перезапуска сервера. В продакшене — один раз на процесс
    (lru_cache): ассеты меняются только при деплое, и все воркеры одного
    деплоя отдают одинаковую версию.
    """
    if settings.DEBUG:
        return {"static_version": _scan_static_version()}
    return {"static_version": _cached_static_version()}


@lru_cache(maxsize=1)
def _cached_static_version() -> str:
    """Версия статики, зафиксированная на время жизни процесса."""
    return _scan_static_version()


def _scan_static_version() -> str:
    """
    Номер от времени изменения самого свежего файла в static/.

    Раньше здесь стоял int(time.time()): номер менялся каждую секунду,
    и браузер перекачивал все CSS и JS при каждом визите вместо того,
    чтобы взять их из кэша. Теперь версия меняется только когда меняются
    сами ассеты. Git-ревизию не берём: в образе .git отсутствует
    (.dockerignore), а mtime работает везде — и в разработке, и в контейнере.
    """
    latest = 0.0
    for entry in getattr(settings, "STATICFILES_DIRS", ()):
        # В STATICFILES_DIRS могут лежать пары (префикс, путь).
        base = entry[1] if isinstance(entry, (list, tuple)) else entry
        for dirpath, _dirnames, filenames in os.walk(base):
            for filename in filenames:
                try:
                    mtime = os.path.getmtime(os.path.join(dirpath, filename))
                except OSError:
                    continue
                latest = max(latest, mtime)
    return f"m{int(latest)}"


def lb_topnav(request):
    """Верхняя навигация — одинаковая на всех страницах."""
    from apps.catalog.models import Title

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
    return {"lb_topnav": links}


def lb_sidebar(request):
    """
    Данные боковой панели каталога — для любой страницы сайта.

    Раньше панель с категориями, годами, подборками и обновлениями была
    свёрстана внутри home.html и получала данные из HomeView. Поэтому она
    существовала только на главной: на каталоге показывалась другая панель,
    а на подборках и персонах не было никакой. Здесь собраны ключи для обеих,
    чтобы одна и та же разметка работала везде.

    Все источники ниже уже кэшируются сами (get_home_sidebar,
    get_featured_collections, список жанров и годов), поэтому отдельного
    кэша здесь нет — иначе получился бы кэш поверх кэша с двумя разными
    сроками жизни, и сброс одного не сбрасывал бы другой.

    Значения ленивые. Context processor выполняется на каждый ответ, который
    рендерит шаблон, — включая robots.txt, правовые страницы и админку, где
    сайдбара нет вовсе. Раньше он безусловно строил страны, обновления
    сериалов, отзывы, жанры, подборки и годы: на холодном кэше robots.txt
    стоил 16 запросов. SimpleLazyObject откладывает вычисление до первого
    обращения из шаблона, поэтому страницы без сайдбара не платят ничего.

    Вьюха может переопределить любой из этих ключей: её контекст важнее,
    и тогда ленивое значение так и остаётся невычисленным.
    """
    from apps.catalog.forms import get_year_choices
    from apps.catalog.services import get_featured_collections, get_home_sidebar
    from apps.catalog.views import _get_cached_genre_chip_list

    def from_sidebar(key):
        """Ключ общего блока сайдбара. Сам блок кэшируется одним куском."""
        return SimpleLazyObject(lambda: get_home_sidebar()[key])

    # Пустой год отбрасываем: в списке выбора он означает «любой»
    # и в навигации по годам смысла не имеет.
    return {
        "countries": from_sidebar("countries"),
        "series_updates": from_sidebar("series_updates"),
        "latest_reviews": from_sidebar("latest_reviews"),
        "genres": SimpleLazyObject(lambda: _get_cached_genre_chip_list(50)),
        "collections": SimpleLazyObject(get_featured_collections),
        "lb_years": SimpleLazyObject(
            lambda: [int(year) for year, _ in get_year_choices() if year]
        ),
        "lb_country_links": SimpleLazyObject(
            lambda: _curated_country_links(get_home_sidebar()["countries"])
        ),
        "lb_series_links": SimpleLazyObject(_series_links),
    }


def _curated_country_links(countries):
    """
    Курированные ссылки «По странам»: не полный список, а пара десятков
    самых ходовых с прилагательным в подписи («Американские», «Корейские»).
    """
    from django.urls import reverse

    by_name = {country.name: country for country in countries}
    curated = [
        ("США", "Американские"),
        ("Россия", "Российские"),
        ("Индия", "Индийские"),
        ("Южная Корея", "Корейские"),
        ("Великобритания", "Английские"),
    ]
    return [
        (reverse("catalog:country_titles", args=[by_name[name].slug]), label)
        for name, label in curated
        if name in by_name
    ]


def _series_links():
    """Ссылки блока «Сериалы» сайдбара."""
    from django.urls import reverse

    catalog_url = reverse("catalog:title_list")
    return [
        ("Все сериалы", f"{catalog_url}?type=series"),
        ("Фильмы", f"{catalog_url}?type=movie"),
        ("Подборки", reverse("catalog:collection_list")),
    ]
