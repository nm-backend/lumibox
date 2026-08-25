import os
from functools import lru_cache

from django.conf import settings
from django.urls import reverse
from django.utils.functional import SimpleLazyObject
from django.utils.translation import gettext as _


def global_settings(request):
    return {
        "ga_measurement_id": getattr(settings, "GA_MEASUREMENT_ID", ""),
        # Рекламная сеть — отдельная опция, выключенная по умолчанию.
        # В шаблоне тег <ins id="vibix_union"> и скрипт-лоадер подключаются
        # только когда ads_network.enabled истинно.
        "ads_network": {
            "enabled": settings.ADS_NETWORK_ENABLED,
            "publisher_id": settings.ADS_NETWORK_PUBLISHER_ID,
            "add_types": settings.ADS_NETWORK_ADD_TYPES,
        },
    }


def static_version(request):
    """
    Стабильный номер версии статики для cache-busting (?v=...).

    В разработке считаем на каждый запрос: правка CSS/JS должна быть видна
    сразу, без перезапуска сервера. В продакшене — один раз на процесс
    (lru_cache): ассеты меняются только при деплое, и все воркеры одного
    деплоя отдают одинаковую версию.
    """
    return {"static_version": static_version_value()}


def static_version_value() -> str:
    """
    Та же версия, но как значение — её просит и шаблонный тег иконок.

    В разработке считаем на каждый запрос: правка CSS/JS должна быть видна
    сразу, без перезапуска сервера. В продакшене — один раз на процесс.
    """
    if settings.DEBUG:
        return _scan_static_version()
    return _cached_static_version()


@lru_cache(maxsize=1)
def _cached_static_version() -> str:
    """Версия статики, зафиксированная на время жизни процесса."""
    return _scan_static_version()


def _scan_static_version() -> str:
    """
    Версия статики, рассчитанная по хешу содержимого CSS/JS файлов.

    Раньше использовался mtime (время модификации), но в Docker bind mounts
    на macOS/Windows mtime не всегда обновляется корректно — файл на хосте
    меняется, а внутри контейнера (и в заголовке Last-Modified) остаётся
    старое значение. Браузер получает тот же ?v=… и отдаёт кэшированный CSS.

    Хеш MD5 от содержимого файлов надёжнее: он меняется только когда файл
    реально изменился, и не зависит от файловой системы. Берём только
    CSS/JS — шрифты, изображения и прочее не влияют на UI-версию.
    """
    import hashlib

    h = hashlib.md5()
    extensions = {".css", ".js"}
    for entry in getattr(settings, "STATICFILES_DIRS", ()):
        base = entry[1] if isinstance(entry, (list, tuple)) else entry
        for dirpath, _dirnames, filenames in os.walk(base):
            for filename in sorted(filenames):
                if os.path.splitext(filename)[1].lower() not in extensions:
                    continue
                filepath = os.path.join(dirpath, filename)
                try:
                    with open(filepath, "rb") as f:
                        for chunk in iter(lambda: f.read(8192), b""):
                            h.update(chunk)
                except OSError:
                    continue
    return h.hexdigest()[:12]


def lb_topnav(request):
    """Верхняя навигация — одинаковая на всех страницах.

    Активный пункт определяется сервером (без JS), чтобы подсветка
    переживала перезагрузку и работала без скриптов:
    - явный ?type=… в адресе решает сам;
    - страница тайтла подсвечивает раздел своего типа;
    - остальные страницы каталога (жанр, страна, год, студия) относятся
      к семейству каталога — без явного типа подсвечивается «Фильмы»
      как раздел по умолчанию;
    - поиск и служебные списки (популярное, топ, справочники) ничего
      не подсвечивают: они не являются пунктами этой навигации.
    """
    from apps.catalog.models import Title

    catalog_url = reverse("catalog:title_list")
    match = getattr(request, "resolver_match", None)
    url_name = getattr(match, "url_name", "") or ""
    get = request.GET

    valid_types = {str(value) for value, _label in Title.Type.choices}
    active_type = get.get("type") if get.get("type") in valid_types else None

    if active_type is None:
        if url_name == "title_detail":
            slug = (getattr(match, "kwargs", None) or {}).get("slug")
            if slug:
                active_type = (
                    Title.objects.filter(slug=slug)
                    .values_list("type", flat=True)
                    .first()
                )
        elif url_name in {
            "title_list",
            "genre_titles",
            "country_titles",
            "year_titles",
            "studio_detail",
        }:
            active_type = str(Title.Type.MOVIE)

    def by_type(label, value):
        return (label, f"{catalog_url}?type={value}", active_type == str(value))

    # Ключ активного раздела для мобильного меню (drawer): те же правила.
    active_key = None
    if url_name == "home":
        active_key = "home"
    elif active_type:
        active_key = active_type
    elif url_name == "new":
        active_key = "new"
    elif url_name == "premieres":
        active_key = "premieres"
    elif url_name in ("collection_list", "collection_detail"):
        active_key = "collections"

    links = [
        (_("Главная"), reverse("catalog:home"), url_name == "home"),
        by_type(_("Фильмы"), Title.Type.MOVIE),
        by_type(_("Сериалы"), Title.Type.SERIES),
        by_type(_("Мультфильмы"), Title.Type.CARTOON),
        by_type(_("ТВ-шоу"), Title.Type.TV_SHOW),
        # Новинки и премьеры — собственные разделы, а не сортировка каталога:
        # у раздела свой адрес, заголовок и место в поиске.
        (_("Новинки"), reverse("catalog:new"), url_name == "new"),
        (_("Скоро"), reverse("catalog:premieres"), url_name == "premieres"),
        (_("Подборки"), reverse("catalog:collection_list"),
         url_name in ("collection_list", "collection_detail")),
    ]
    return {"lb_topnav": links, "lb_topnav_active": active_key}


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
        "coming_soon": from_sidebar("coming_soon"),
        "latest_comments": from_sidebar("latest_comments"),
        "genres": SimpleLazyObject(lambda: _get_cached_genre_chip_list(50)),
        "collections": SimpleLazyObject(get_featured_collections),
        "lb_years": SimpleLazyObject(
            lambda: [int(year) for year, _ in get_year_choices() if year]
        ),
        "lb_country_links": SimpleLazyObject(
            lambda: _curated_country_links(get_home_sidebar()["countries"])
        ),
        "lb_series_links": SimpleLazyObject(_series_links),
        # Топ популярного берём из того же кэшированного блока сайдбара,
        # что и остальные ключи (countries, series_updates, latest_reviews):
        # отдельный запрос на каждую страницу противоречил бы схеме
        # «лениво и из кэша». Сам ключ собирает get_home_sidebar, где
        # «популярное» отфильтровано по views_count > 0 — иначе блок
        # вырождается в «последние добавленные», и чужие тайтлы мелькают
        # в сайдбаре на страницах избранного/списков.
        "lb_most_viewed": from_sidebar("most_viewed"),
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
    """
    Ссылки блока «Сериалы» сайдбара.

    Подписи проходят через gettext: раньше это были обычные строки Python,
    и на английской с кыргызской версиях блок оставался русским.
    """
    from django.urls import reverse

    catalog_url = reverse("catalog:title_list")
    return [
        (_("Все сериалы"), f"{catalog_url}?type=series"),
        (_("Мультфильмы"), f"{catalog_url}?type=cartoon"),
        (_("ТВ-шоу"), f"{catalog_url}?type=tv_show"),
        (_("Фильмы"), f"{catalog_url}?type=movie"),
        (_("Подборки"), reverse("catalog:collection_list")),
    ]
