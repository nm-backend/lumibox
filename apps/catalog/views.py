from random import randrange

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import DetailView, ListView, TemplateView

from apps.catalog.forms import CatalogFilterForm
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
from apps.library.models import Favorite
from apps.library.services import remember_view
from apps.reviews.forms import ReviewForm
from apps.reviews.models import Review
from apps.streaming.services import get_continue_watching, get_watch_url

# Условие «считать только опубликованное» для annotate(Count(...)).
# Вынесено в константу: используется и для жанров, и для стран.
PUBLISHED_TITLES = Q(titles__status=Title.Status.PUBLISHED)

# Ключ кэша для списка жанров в навигации.
# Отдельный от GenreListView — там данные другие (titles_count sorted).
GENRE_CHIPS_CACHE_KEY = "catalog:genre_chips:v2"


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
            context["continue_watching"] = get_continue_watching(self.request.user)

        context["collections"] = get_featured_collections()

        context["genres"] = _get_cached_genre_chip_list(12)
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
        # defer("description"): на списке не нужно описание, только в карточке.
        # Без этого текстовое поле тянется на каждую из 24 записей —
        # лишние мегабайты в ответе сервера.
        return Title.objects.published().with_related().defer("description")

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
    # сходит в базу за каждым именем отдельно.
    # Рейтинг брать неоткуда не нужно: он лежит готовым в полях модели.
    # prefetch_related("seasons__episodes__video_asset") подтягивает
    # сезоны с сериями и их видеоресурсами — без N+1 во вкладке сезонов.
    queryset = Title.objects.published().with_related().with_crew().prefetch_related(
        "seasons__episodes__video_asset"
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
        context["watch_url"] = get_watch_url(self.object)
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


class PersonDetailView(DetailView):
    """Страница персоны: фильмография, разложенная по ролям."""

    model = Person
    template_name = "catalog/person_detail.html"
    context_object_name = "person"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Фильмография: только опубликованное, с ролью человека в каждом проекте.
        context["participations"] = (
            Participation.objects.filter(
                person=self.object,
                title__status=Title.Status.PUBLISHED,
            )
            .select_related("title")
            .prefetch_related("title__genres")
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
        return Title.objects.published().with_related().filter(studios=self.studio).defer("description")

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
        award_pks = (
            Title.objects.published()
            .filter(award_entries__award=self.award)
            .values_list("pk", flat=True)
            .distinct()
        )
        return (
            Title.objects.published()
            .with_related()
            .filter(pk__in=award_pks)
            .order_by("-award_entries__year", "name")
            .defer("description")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["entity"] = self.award
        context["entity_label"] = "Премия"
        return context


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
        return Title.objects.published().with_related().in_collection(self.collection).defer("description")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["collection"] = self.collection
        return context
