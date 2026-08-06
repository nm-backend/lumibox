from random import randrange

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, F, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import DetailView, ListView, TemplateView

from apps.catalog.forms import CatalogFilterForm
from apps.catalog.managers import story_card_prefetches
from apps.catalog.models import Award, Collection, Country, Genre, Person, Studio, Title
from apps.catalog.models.person import Participation
from apps.catalog.services import (
    REFERENCE_COUNTRY_CACHE_KEY,
    REFERENCE_GENRE_CACHE_KEY,
    get_crew_by_role,
    get_featured_collections,
    get_home_sections,
    get_recommendations,
    get_similar_titles,
)
from apps.core.views import ElidedPaginationMixin
from apps.library.models import Favorite, WatchHistory, Watchlist
from apps.library.services import remember_view
from apps.reviews.forms import ReviewForm
from apps.reviews.models import Review

# Условие «считать только опубликованное» для annotate(Count(...)).
# Вынесено в константу: используется и для жанров, и для стран.
PUBLISHED_TITLES = Q(titles__status=Title.Status.PUBLISHED)

# Ключ кэша для списка жанров в навигации.
# Отдельный от GenreListView — там данные другие (titles_count sorted).
GENRE_CHIPS_CACHE_KEY = "catalog:genre_chips:v2"


def _dedup_titles(*groups):
    """Объединяет списки записей без повторов, сохраняя порядок."""
    seen = set()
    result = []
    for group in groups:
        for title in group:
            if title.pk not in seen:
                seen.add(title.pk)
                result.append(title)
    return result


def _get_cached_genre_chip_list(limit=50):
    """
    Кэшированный список жанров с количеством фильмов.

    Этот запрос выполняется на каждой загрузке главной и каталога.
    Жанры меняются редко — кэш на час.
    Возвращает list для совместимости с шаблоном (можно итерировать).
    """
    cached = cache.get(GENRE_CHIPS_CACHE_KEY)
    if cached is not None:
        return cached[:limit] if len(cached) > limit else cached

    qs = list(
        Genre.objects.annotate(titles_count=Count("titles", filter=PUBLISHED_TITLES))
        .filter(titles_count__gt=0)
        .order_by("name")
    )
    cache.set(GENRE_CHIPS_CACHE_KEY, qs, 60 * 60)
    return qs[:limit] if len(qs) > limit else qs


class HomeView(TemplateView):
    """
    Главная страница: баннер и несколько подборок.

    Каждая подборка — отдельный запрос, но все они с limit и prefetch,
    поэтому страница остаётся лёгкой. Когда подключим Redis, результаты
    этих запросов будут кэшироваться целиком.
    """

    template_name = "catalog/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Пять запросов главной берём из кэша одним куском.
        # Баннер — свежая публикация с описанием: пустой выглядел бы сломанным.
        context.update(get_home_sections())

        # Адреса подборок собираем из маршрута, а не пишем строкой в шаблоне:
        # поменяется адрес каталога — здесь всё останется рабочим.
        catalog_url = reverse("catalog:title_list")
        context["new_url"] = f"{catalog_url}?sort=-published_at"
        context["top_rated_url"] = f"{catalog_url}?sort=-rating_average"
        context["movies_url"] = f"{catalog_url}?type={Title.Type.MOVIE}"
        context["series_url"] = f"{catalog_url}?type={Title.Type.SERIES}"

        # Гостю блок рекомендаций не показываем, поэтому и не считаем:
        # лишний запрос на каждой загрузке главной ни к чему.
        if self.request.user.is_authenticated:
            context["recommendations"] = get_recommendations(self.request.user)

        context["collections"] = get_featured_collections()

        # Жанры для панели навигации в сайдбаре — все, с количеством фильмов.
        context["genres"] = _get_cached_genre_chip_list(50)
        from apps.catalog.services import (
            get_home_sidebar,
            get_home_statistics,
            get_trending_titles,
        )
        context["statistics"] = get_home_statistics()
        context["trending"] = get_trending_titles()

        # Сайдбар и панель навигации главной.
        context.update(get_home_sidebar())
        from apps.catalog.forms import get_year_choices
        context["lb_years"] = [int(year) for year, _ in get_year_choices() if year]

        # Выпадающий список «Сортировать» панели xSort.
        context["lb_sort_links"] = [
            ("по дате", f"{catalog_url}?sort=-published_at"),
            ("по рейтингу", f"{catalog_url}?sort=-rating_average"),
            ("топ за неделю", catalog_url),
            ("по комментариям", f"{catalog_url}?sort=-rating_count"),
            ("по году", f"{catalog_url}?sort=-release_year"),
        ]

        # Лента главной: популярное за неделю, затем топ по рейтингу,
        # добитый новинками. Карусель: популярное за неделю, добитое новинками.
        # 8 карточек: высота страницы подогнана под высоту ленты.
        context["home_titles"] = _dedup_titles(
            context.get("trending", []),
            context.get("top_rated", []),
            context.get("new_titles", []),
        )[:8]
        context["lb_carousel"] = _dedup_titles(
            context.get("trending", []), context.get("new_titles", [])
        )[:14]

        # Пагинация как в каталоге: 24 записи на страницу, ссылки ведут
        # на страницы каталога, поэтому номера совпадают.
        from math import ceil

        context["lb_pages"] = max(
            1, ceil(context.get("statistics", {}).get("published_count", 0) / 24)
        )
        return context


class TitleListView(ElidedPaginationMixin, ListView):
    """
    Каталог фильмов и сериалов.

    Всю фильтрацию выполняет CatalogFilterForm — вьюха только собирает
    контекст. Страницы жанра и страны наследуются отсюда и лишь сужают
    исходный queryset, поэтому логика списка описана один раз.
    """

    template_name = "catalog/title_list.html"
    context_object_name = "titles"
    paginate_by = 24

    page_heading = "Каталог"
    page_subtitle = ""

    def get_filter_form(self):
        # Форма нужна и в get_queryset, и в контексте — создаём один раз.
        if not hasattr(self, "_filter_form"):
            self._filter_form = CatalogFilterForm(self.request.GET or None)
        return self._filter_form

    def get_base_queryset(self):
        """Точка расширения для страниц жанра и страны."""
        return Title.objects.published().with_related().with_progress(self.request.user)

    def get_queryset(self):
        return self.get_filter_form().filter(self.get_base_queryset())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = self.get_filter_form()

        context["filter_form"] = form
        context["active_filters"] = self.build_active_filters(form)
        context["page_heading"] = self.page_heading
        context["page_subtitle"] = self.page_subtitle
        # Genre chips for quick filter navigation
        context["genres"] = _get_cached_genre_chip_list()
        return context

    def build_active_filters(self, form):
        """
        Добавляет к каждому применённому фильтру ссылку «убрать».

        Ссылка — это текущий адрес без одного параметра. Заодно сбрасываем
        page: после снятия фильтра результатов меньше, и страница №5
        могла бы просто перестать существовать.
        """
        filters = []

        for field, label in form.active_filter_labels():
            query = self.request.GET.copy()
            query.pop(field, None)
            query.pop("page", None)
            remaining = query.urlencode()
            filters.append({
                "label": label,
                "remove_url": f"{self.request.path}?{remaining}" if remaining else self.request.path,
            })

        return filters


class GenreTitleListView(TitleListView):
    """Каталог, суженный до одного жанра: /genres/drama/"""

    page_subtitle = "Жанр"

    def get_base_queryset(self):
        genre = get_object_or_404(Genre, slug=self.kwargs["slug"])
        self.page_heading = genre.name
        return super().get_base_queryset().filter(genres=genre)


class CountryTitleListView(TitleListView):
    """Каталог, суженный до одной страны: /countries/yaponiya/"""

    page_subtitle = "Страна"

    def get_base_queryset(self):
        country = get_object_or_404(Country, slug=self.kwargs["slug"])
        self.page_heading = country.name
        return super().get_base_queryset().filter(countries=country)


class ReferenceListView(ListView):
    """
    Общий список справочника — жанров или стран.

    Показывает только непустые: ссылка на жанр без единого фильма
    ведёт посетителя в тупик.
    """

    template_name = "catalog/reference_list.html"
    context_object_name = "references"

    page_heading = ""
    detail_url_name = ""

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .annotate(titles_count=Count("titles", filter=PUBLISHED_TITLES))
            .filter(titles_count__gt=0)
            # Возвращаем алфавит: annotate строит GROUP BY и сбрасывает
            # ordering из Meta, после чего жанры выводились в том порядке,
            # в каком их вернула СУБД, — то есть в произвольном.
            .order_by("name")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_heading"] = self.page_heading
        context["detail_url_name"] = self.detail_url_name
        return context


class GenreListView(ReferenceListView):
    model = Genre
    page_heading = "Жанры"
    detail_url_name = "catalog:genre_titles"

    def get_queryset(self):
        """
        Кэшированный список жанров.

        Возвращает list — это корректно для ReferenceListView, у которого
        нет пагинации и method в контексте. Шаблон только итерирует
        по references и читает атрибуты. Сохраняем аннотацию titles_count
        и избегаем лишних запросов к БД при попадании в кэш.
        """
        cached = cache.get(REFERENCE_GENRE_CACHE_KEY)
        if cached is not None:
            return cached
        qs = list(super().get_queryset())
        cache.set(REFERENCE_GENRE_CACHE_KEY, qs, settings.CACHE_TTL_REFERENCE)
        return qs


class CountryListView(ReferenceListView):
    model = Country
    page_heading = "Страны"
    detail_url_name = "catalog:country_titles"

    def get_queryset(self):
        """
        Кэшированный список стран.

        Возвращает list — это корректно для ReferenceListView, у которого
        нет пагинации. Шаблон только итерирует и читает атрибуты.
        """
        cached = cache.get(REFERENCE_COUNTRY_CACHE_KEY)
        if cached is not None:
            return cached
        qs = list(super().get_queryset())
        cache.set(REFERENCE_COUNTRY_CACHE_KEY, qs, settings.CACHE_TTL_REFERENCE)
        return qs


class TitleDetailView(DetailView):
    """Страница фильма или сериала."""

    template_name = "catalog/title_detail.html"
    context_object_name = "title"

    # Черновик по прямой ссылке отдаёт 404.
    # with_crew подтягивает съёмочную группу заранее — иначе шаблон
    # сходит в базу за каждым именем отдельно. with_frames — кадры галереи:
    # шаблон обращается к ним дважды, и каждый вызов без prefetch был
    # отдельным запросом. with_episodes — серии для плеера и метаданных.
    # Рейтинг брать неоткуда не нужно: он лежит готовым в полях модели.
    queryset = (
        Title.objects.published()
        .with_related()
        .with_crew()
        .with_frames()
        .with_episodes()
    )

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        # Запоминаем просмотр после успешной отрисовки страницы.
        remember_view(request.user, self.object)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_review = self.get_user_review()

        context["similar_titles"] = get_similar_titles(self.object)
        context["crew_by_role"] = get_crew_by_role(self.object)
        context["reviews"] = self.object.reviews.published().with_author()
        context["review_form"] = ReviewForm(instance=user_review)
        context["user_review"] = user_review
        context["is_favorite"] = self.is_favorite()
        context["is_watchlist"] = self.is_watchlist()
        context["resume_episode"] = self.get_resume_episode()

        # Серии уже подтянуты prefetch'ем (with_episodes): обращения к БД
        # здесь нет. Один список эпизодов даёт и секцию плеера, и метаданные
        # «N сезонов · M серий».
        episodes = list(self.object.episodes.all())
        context["episodes"] = episodes
        context["episode_stats"] = (
            {"seasons": len({e.season_number for e in episodes}), "count": len(episodes)}
            if episodes
            else None
        )
        return context

    def get_user_review(self):
        """Отзыв текущего пользователя, если он уже есть."""
        if not self.request.user.is_authenticated:
            return None

        if not hasattr(self, "_user_review"):
            self._user_review = Review.objects.filter(
                user=self.request.user, title=self.object
            ).first()
        return self._user_review

    def is_favorite(self):
        if not self.request.user.is_authenticated:
            return False
        return Favorite.objects.filter(user=self.request.user, title=self.object).exists()

    def is_watchlist(self):
        if not self.request.user.is_authenticated:
            return False
        return Watchlist.objects.filter(user=self.request.user, title=self.object).exists()

    def get_resume_episode(self):
        """
        Последняя серия, с которой пользователь начал смотреть.

        Возвращает: Episode или None. Один запрос к истории: единственная
        строка на пару «пользователь — запись» (unique_watch_history).
        """
        if not self.request.user.is_authenticated:
            return None
        history = WatchHistory.objects.filter(
            user=self.request.user, title=self.object, episode__isnull=False
        ).first()
        return history.episode if history else None


class PersonDetailView(DetailView):
    """Страница персоны: фильмография, разложенная по ролям."""

    model = Person
    template_name = "catalog/person_detail.html"
    context_object_name = "person"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Фильмография: только опубликованное, с ролью человека в каждом проекте.
        # Фильмография рендерится тем же шаблоном карточки, что и каталог,
        # поэтому и связи ей нужны те же. Раньше здесь прегружались только
        # жанры, и карточка добирала персон по одному: восемь лишних
        # запросов на четыре карточки, причём кэш их не снимал.
        context["participations"] = (
            Participation.objects.filter(
                person=self.object,
                title__status=Title.Status.PUBLISHED,
            )
            .select_related("title")
            .prefetch_related(*story_card_prefetches("title__"))
            .order_by("-title__release_year")
        )
        context["awards"] = self.object.award_entries.select_related("award", "title")[:12]
        return context


class PersonDirectoryView(ListView):
    """Каталог актёров или режиссёров с количеством опубликованных работ."""

    template_name = "catalog/person_list.html"
    context_object_name = "persons"
    role = Participation.Role.ACTOR
    page_heading = "Актёры"

    def get_queryset(self):
        published_role = Q(
            participations__role=self.role,
            participations__title__status=Title.Status.PUBLISHED,
        )
        return (
            Person.objects.annotate(titles_count=Count("participations__title", filter=published_role, distinct=True))
            .filter(titles_count__gt=0)
            .order_by("name")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_heading"] = self.page_heading
        return context


class ActorListView(PersonDirectoryView):
    role = Participation.Role.ACTOR
    page_heading = "Актёры"


class DirectorListView(PersonDirectoryView):
    role = Participation.Role.DIRECTOR
    page_heading = "Режиссёры"


class StudioListView(ListView):
    template_name = "catalog/reference_list.html"
    context_object_name = "references"

    def get_queryset(self):
        return (
            Studio.objects.annotate(titles_count=Count("titles", filter=PUBLISHED_TITLES))
            .filter(titles_count__gt=0)
            .order_by("name")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_heading"] = "Студии"
        context["detail_url_name"] = "catalog:studio_detail"
        return context


class StudioDetailView(ElidedPaginationMixin, ListView):
    template_name = "catalog/industry_detail.html"
    context_object_name = "titles"
    paginate_by = 24

    def get_queryset(self):
        self.studio = get_object_or_404(Studio, slug=self.kwargs["slug"])
        return (
            Title.objects.published()
            .with_related()
            .with_progress(self.request.user)
            .filter(studios=self.studio)
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["entity"] = self.studio
        context["entity_label"] = "Студия"
        return context


class AwardListView(ListView):
    template_name = "catalog/reference_list.html"
    context_object_name = "references"

    def get_queryset(self):
        return (
            Award.objects.annotate(
                titles_count=Count(
                    "title_entries__title",
                    filter=Q(title_entries__title__status=Title.Status.PUBLISHED),
                    distinct=True,
                )
            )
            .filter(titles_count__gt=0)
            .order_by("name")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_heading"] = "Награды"
        context["detail_url_name"] = "catalog:award_detail"
        return context


class AwardDetailView(ElidedPaginationMixin, ListView):
    template_name = "catalog/industry_detail.html"
    context_object_name = "titles"
    paginate_by = 24

    def get_queryset(self):
        self.award = get_object_or_404(Award, slug=self.kwargs["slug"])
        # Сортировка по award_entries__year соединяет таблицу наград и тем самым
        # размножает строки: фильм с тремя записями о наградах попадал в список
        # трижды, причём учитывались награды всех премий, а не только текущей.
        # Дубликаты уходили и в счётчик пагинации.
        #
        # annotate после filter агрегирует по уже отфильтрованному соединению,
        # то есть Max берёт год только этой премии, а GROUP BY схлопывает строки
        # обратно в один фильм.
        return (
            Title.objects.published()
            .with_related()
            .with_progress(self.request.user)
            .filter(award_entries__award=self.award)
            .annotate(award_year=Max("award_entries__year"))
            .order_by(F("award_year").desc(nulls_last=True), "name")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["entity"] = self.award
        context["entity_label"] = "Премия"
        return context


class ActorSearchView(TemplateView):
    """
    Поиск фильмов по актёру.

    GET  — форма поиска + результаты, если задан q.
    GET ?q=xxx&json=1 — JSON для AJAX-подсказок.
    """

    template_name = "catalog/actor_search.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        q = self.request.GET.get("q", "").strip()

        context["query"] = q
        context["results"] = None

        if q:
            persons = list(
                Person.objects.filter(name__icontains=q)
                .order_by("name")[:20]
            )

            # Раньше запрос строился внутри цикла по персонам, а prefetch
            # покрывал только жанры — карточке же нужны ещё страны, студии и
            # участники, и она добирала их по одному. На выдаче из 12 человек
            # страница стоила 252 запроса. Забираем все участия разом и
            # раскладываем по людям в памяти.
            participations = (
                Participation.objects.filter(
                    person__in=persons,
                    title__status=Title.Status.PUBLISHED,
                )
                .select_related("title")
                .prefetch_related(*story_card_prefetches("title__"))
                .order_by("-title__release_year")
            )

            grouped = {}
            for participation in participations:
                grouped.setdefault(participation.person_id, []).append(participation)

            context["results"] = [
                {"person": person, "participations": grouped.get(person.pk, [])}
                for person in persons
            ]

        return context

    def get(self, request, *args, **kwargs):
        # AJAX-запрос: возвращаем JSON с подсказками
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            q = request.GET.get("q", "").strip()
            if len(q) < 2:
                return JsonResponse({"results": []})

            persons = (
                Person.objects.filter(name__icontains=q)
                .annotate(
                    film_count=Count(
                        "participations__title",
                        filter=Q(participations__title__status=Title.Status.PUBLISHED),
                        distinct=True,
                    )
                )
                .filter(film_count__gt=0)
                .order_by("name")[:10]
            )

            results = []
            for person in persons:
                item = {
                    "id": person.id,
                    "name": person.name,
                    "original_name": person.original_name,
                    "slug": person.slug,
                    "photo": person.photo.url if person.photo else None,
                    "film_count": person.film_count,
                    "url": person.get_absolute_url(),
                }
                results.append(item)

            return JsonResponse({"results": results})

        return super().get(request, *args, **kwargs)


class RandomTitleView(ListView):
    """Перенаправляет на случайное опубликованное произведение без сортировки ORDER BY RANDOM()."""

    def get(self, request, *args, **kwargs):
        queryset = Title.objects.published().order_by("pk")
        count = queryset.count()
        if not count:
            return redirect("catalog:title_list")
        return redirect(queryset[randrange(count)].get_absolute_url())


class CollectionListView(ElidedPaginationMixin, ListView):
    """Все подборки."""

    template_name = "catalog/collection_list.html"
    context_object_name = "collections"
    paginate_by = 12

    def get_queryset(self):
        # order_by обязателен, хотя он же стоит в Meta.ordering: annotate
        # строит GROUP BY, а для таких запросов Django сбрасывает сортировку
        # модели. Без неё порядок строк отдаёт СУБД, и одна подборка могла
        # бы повториться на второй странице, а другая — исчезнуть совсем.
        return (
            Collection.objects.published()
            .annotate(titles_count=Count("titles", filter=PUBLISHED_TITLES))
            .order_by("order", "-created_at")
        )


class CollectionDetailView(ElidedPaginationMixin, ListView):
    """
    Страница подборки.

    Это ListView, а не DetailView: внутри подборки нужны пагинация
    и сетка карточек. Сама подборка кладётся в контекст отдельно.
    """

    template_name = "catalog/collection_detail.html"
    context_object_name = "titles"
    paginate_by = 24

    def get_queryset(self):
        self.collection = get_object_or_404(
            Collection.objects.published(), slug=self.kwargs["slug"]
        )
        return (
            Title.objects.published()
            .with_related()
            .with_progress(self.request.user)
            .in_collection(self.collection)
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["collection"] = self.collection
        return context
