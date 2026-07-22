from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import DetailView, ListView, TemplateView

from apps.catalog.forms import CatalogFilterForm
from apps.catalog.models import Collection, Country, Genre, Person, Title
from apps.catalog.models.person import Participation
from apps.catalog.services import (
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

# Условие «считать только опубликованное» для annotate(Count(...)).
# Вынесено в константу: используется и для жанров, и для стран.
PUBLISHED_TITLES = Q(titles__status=Title.Status.PUBLISHED)


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

        context["genres"] = (
            Genre.objects.annotate(titles_count=Count("titles", filter=PUBLISHED_TITLES))
            .filter(titles_count__gt=0)
            .order_by("-titles_count")[:12]
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
        return Title.objects.published().with_related()

    def get_queryset(self):
        return self.get_filter_form().filter(self.get_base_queryset())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = self.get_filter_form()

        context["filter_form"] = form
        context["active_filters"] = self.build_active_filters(form)
        context["page_heading"] = self.page_heading
        context["page_subtitle"] = self.page_subtitle
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


class CountryListView(ReferenceListView):
    model = Country
    page_heading = "Страны"
    detail_url_name = "catalog:country_titles"


class TitleDetailView(DetailView):
    """Страница фильма или сериала."""

    template_name = "catalog/title_detail.html"
    context_object_name = "title"

    # Черновик по прямой ссылке отдаёт 404.
    # with_crew подтягивает съёмочную группу заранее — иначе шаблон
    # сходит в базу за каждым именем отдельно.
    # Рейтинг брать неоткуда не нужно: он лежит готовым в полях модели.
    queryset = Title.objects.published().with_related().with_crew()

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
        return context


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
        return Title.objects.published().with_related().in_collection(self.collection)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["collection"] = self.collection
        return context
