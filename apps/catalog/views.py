from random import randrange
from time import time

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

# Сколько постеров показывает промо-блок главной. Константа, а не число
# по месту: шаблон и вьюха должны договориться об одном значении, иначе
# снова начнём прегружать карточки, которые никто не увидит.
PROMO_POSTERS = 4


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

        # Секции главной берём из кэша одним куском.
        context.update(get_home_sections())

        catalog_url = reverse("catalog:title_list")

        # Здесь заводились ещё new_url / top_rated_url / movies_url / series_url —
        # их не читал ни один шаблон. Ссылки на разделы каталога живут в
        # верхней навигации (context processor lb_topnav) и в сайдбаре.

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
        # «топ за неделю» тут нет: тренды считаются отдельным механизмом
        # (см. get_trending_titles), и сортировки каталога с таким именем
        # не существует — обещание, которое каталог не выполняет.
        context["lb_sort_links"] = [
            ("по дате", f"{catalog_url}?sort=-published_at"),
            ("по рейтингу", f"{catalog_url}?sort=-rating_average"),
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
        # Постеры промо-блока. Ровно столько, сколько рисует шаблон: раньше
        # здесь собиралось 14 объектов со всеми связями, а промо показывало
        # четыре — десять карточек прегружались и выбрасывались.
        context["lb_carousel"] = _dedup_titles(
            context.get("trending", []), context.get("new_titles", [])
        )[:PROMO_POSTERS]

        # Бейдж «Продолжить с S1E3» на главной. Секции главной приходят
        # из кэша, поэтому прогресс нельзя вешать на их объекты атрибутом:
        # LocMemCache вернул бы чужой прогресс другому пользователю.
        # Пересобираем объекты свежим запросом с prefetch истории.
        if self.request.user.is_authenticated:
            ids = {t.pk for t in context["home_titles"] + context["lb_carousel"]}
            fresh = {
                t.pk: t
                for t in Title.objects.published().filter(pk__in=ids).with_progress(self.request.user)
            }
            context["home_titles"] = [fresh.get(t.pk, t) for t in context["home_titles"]]
            context["lb_carousel"] = [fresh.get(t.pk, t) for t in context["lb_carousel"]]

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

        # Панель быстрых сортировок — сохраняем уже
        # применённые фильтры (жанр, страна, тип), меняя только sort.
        context["lb_sort_links"] = self._sort_links()
        return context

    def _sort_links(self):
        """Ссылки быстрой сортировки: текущий фильтр + новая сортировка.

        Возвращает список (подпись, url, активна_ли). Активность считаем
        здесь, а не в шаблоне: у сортировки «по дате» sort-параметра нет
        (это значение по умолчанию), и сравнение строк в шаблоне
        получилось бы хрупким.

        Базой ссылки служит request.path, а не reverse('catalog:title_list'):
        панель рендерится и на страницах жанра/страны, и там путь несёт
        фильтр (/genres/drama/), который в GET не попадёт — reverse()
        выбрасывал бы его, уводя на весь каталог.
        """
        catalog_url = self.request.path
        base = self.request.GET.copy()
        base.pop("page", None)
        # Сортировку по умолчанию («по дате обновления») каталог применяет
        # и при явном sort=-published_at (из «Новинок») — считаем обе
        # равнозначными активному состоянию панели.
        current = self.request.GET.get("sort", "")
        links = []
        for sort, label in (
            ("", "По дате обновления"),
            ("-views_count", "По просмотрам"),
            ("-rating_average", "По рейтингу"),
            ("-release_year", "По году"),
        ):
            query = base.copy()
            if sort:
                query["sort"] = sort
            else:
                query.pop("sort", None)
            url = f"{catalog_url}?{query.urlencode()}" if query else catalog_url
            is_active = current == sort or (sort == "" and current == "-published_at")
            links.append((label, url, is_active))
        return links

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
        .with_detail()
        .with_frames()
        .with_episodes()
        .with_sources()
    )

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        # Запоминаем просмотр после успешной отрисовки страницы.
        remember_view(request.user, self.object)
        # Счётчик просмотров тоже растёт здесь, но не на каждый заход:
        # одна сессия засчитывает один просмотр на запись (защита от накрутки
        # при обновлении страницы). Гость и авторизованный учитываются одинаково.
        self._count_view(request)
        return response

    def _count_view(self, request):
        """Увеличивает views_count не чаще раза в сутки на запись.

        Значение ключа — метка времени последнего засчитанного просмотра.
        Сверяем её, а не просто «ключ есть»: это позволяет отпускать ключ
        через сутки, не трогая set_expiry всей сессии (продлевать жизнь
        логина и CSRF-токена на каждый просмотр не хочется).
        """
        key = f"viewed:{self.object.pk}"
        last_seen = request.session.get(key)
        now = int(time())
        if last_seen and now - last_seen < 60 * 60 * 24:
            return
        request.session[key] = now
        self.object.increment_views()

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
        context["resume_position"] = self.get_resume_position()

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
        context.update(self.get_playback(episodes))
        context.update(self.get_comments())
        return context

    def get_comments(self):
        """
        Лента обсуждения: верхний уровень с прегруженными ответами.

        Два запроса вместо N+1: корневые комментарии и один prefetch ответов.
        Скрытые модератором не попадают ни туда, ни туда — ответ на скрытый
        комментарий читается как обрывок разговора.

        Счётчик считаем в памяти: объекты уже здесь, отдельный COUNT был бы
        третьим запросом ради числа, которое и так известно.
        """
        from django.db.models import Prefetch

        from apps.reviews.forms import CommentForm
        from apps.reviews.models import Comment

        comments = list(
            Comment.objects.published()
            .roots()
            .with_author()
            .filter(title=self.object)
            .prefetch_related(
                Prefetch(
                    "replies",
                    queryset=Comment.objects.published().select_related("user"),
                    to_attr="visible_replies",
                )
            )
        )
        total = len(comments) + sum(len(comment.visible_replies) for comment in comments)

        return {
            "comments": comments,
            "comments_count": total,
            "comment_form": CommentForm(),
        }

    def get_playback(self, episodes):
        """
        Раскладывает источники видео по сериям.

        Шаблон не умеет искать по словарю, поэтому список источников каждой
        серии вешаем прямо на объект серии — тот самый приём, что и с
        progress_item в карточке каталога. Источники уже в памяти
        (with_sources), новых запросов здесь нет.

        Возвращает ключи:
        - playback_voices — озвучки в порядке появления, для выбора в плеере;
        - title_sources — источники записи целиком (у фильма их и используем);
        - primary_source — что открыть сразу: продолжаем с той серии,
          на которой остановился зритель, иначе с первой.
        """
        sources = list(self.object.playback_sources.all())

        by_episode = {}
        title_sources = []
        for source in sources:
            if source.episode_id:
                by_episode.setdefault(source.episode_id, []).append(source)
            else:
                title_sources.append(source)

        for episode in episodes:
            episode.sources = by_episode.get(episode.pk, [])

        voices, seen = [], set()
        for source in sources:
            if source.voice_id and source.voice_id not in seen:
                seen.add(source.voice_id)
                voices.append(source.voice)

        resume = self.get_resume_episode()
        opening = resume or (episodes[0] if episodes else None)
        candidates = by_episode.get(opening.pk, []) if opening else title_sources
        primary = candidates[0] if candidates else (title_sources[0] if title_sources else None)

        return {
            "playback_voices": voices,
            "title_sources": title_sources,
            "primary_source": primary,
            "has_playback": bool(sources),
        }

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

    def get_history(self):
        """
        Строка истории просмотра текущего пользователя, если она есть.

        Один запрос: строка на пару «пользователь — запись» единственная
        (unique_watch_history). Результат запоминаем — его спрашивают и
        серия для продолжения, и позиция, и раскладка источников.
        """
        if hasattr(self, "_history"):
            return self._history

        if not self.request.user.is_authenticated:
            self._history = None
            return None

        self._history = (
            WatchHistory.objects.select_related("episode")
            .filter(user=self.request.user, title=self.object)
            .first()
        )
        return self._history

    def get_resume_episode(self):
        """Серия, с которой продолжаем. None — смотреть не начинали."""
        history = self.get_history()
        return history.episode if history else None

    def get_resume_position(self):
        """
        Секунда, с которой продолжаем.

        Ноль отдаём и когда прогресса нет, и когда он в самом начале:
        для плеера это одно и то же — играть сначала.
        """
        history = self.get_history()
        return history.position_seconds if history else 0


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
            .prefetch_related(*story_card_prefetches("title__", user=self.request.user))
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
                .annotate(
                    published_works=Count(
                        "participations",
                        filter=Q(participations__title__status=Title.Status.PUBLISHED),
                    )
                )
                .filter(published_works__gt=0)
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
                .prefetch_related(*story_card_prefetches("title__", user=self.request.user))
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
