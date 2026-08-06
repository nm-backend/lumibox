from django.db import IntegrityError
from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_field,
    extend_schema_view,
)
from rest_framework import filters, mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.permissions import IsAuthorOrReadOnly
from apps.api.v1.serializers import (
    CollectionSerializer,
    CountrySerializer,
    GenreSerializer,
    ReviewSerializer,
    TitleDetailSerializer,
    TitleListSerializer,
)
from apps.catalog.models import Collection, Country, Episode, Genre, Person, Title
from apps.catalog.services import get_similar_titles
from apps.library.services import remember_episode_start, toggle_favorite, toggle_watchlist
from apps.reviews.models import Review


class StableOrderingFilter(filters.OrderingFilter):
    """
    OrderingFilter с гарантированно детерминированным порядком.

    DRF при сортировке заменяет порядок модели одной колонкой, выбранной
    клиентом. Год, имя и рейтинг неуникальны, поэтому при листании
    постранично записи-близнецы могут поменяться местами: одна придёт
    дважды, другая пропадёт. Добавляем уникальный «pk» последним ключом.
    """

    def get_ordering(self, request, queryset, view):
        ordering = super().get_ordering(request, queryset, view)
        if not ordering:
            return ordering
        result = []
        for item in ordering:
            if item == "-rating_average":
                # Как в веб-каталоге: неоценённые записи уходят в конец,
                # а не встают первыми (PostgreSQL ставит NULL вперёд при убывании).
                result.append(F("rating_average").desc(nulls_last=True))
            elif item == "rating_average":
                result.append(F("rating_average").asc(nulls_last=False))
            else:
                result.append(item)
        if "pk" not in ordering and "-pk" not in ordering:
            result.append("pk")
        return result


class RateRequestSerializer(serializers.Serializer):
    """Оценка фильма или сериала от 1 до 10."""

    rating = serializers.IntegerField(min_value=1, max_value=10)


class EpisodeWatchRequestSerializer(serializers.Serializer):
    """Номер серии, которую пользователь начал смотреть."""

    episode = serializers.IntegerField()


class SearchResultSerializer(serializers.Serializer):
    """Результат глобального поиска по каталогу."""
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.SlugField()
    type = serializers.CharField()
    release_year = serializers.IntegerField()
    poster = serializers.SerializerMethodField()
    url = serializers.CharField(source="get_absolute_url", read_only=True)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_poster(self, obj):
        return obj.poster.url if obj.poster else None


class FavoriteResponseSerializer(serializers.Serializer):
    """
    Ответ переключателя избранного.

    Существует только ради схемы: сама вьюха отдаёт обычный словарь,
    и без этого класса в документации на его месте была бы пустота.
    """

    is_favorite = serializers.BooleanField(
        help_text="True — запись теперь в избранном, False — убрана из него",
    )


class WatchlistResponseSerializer(serializers.Serializer):
    """
    Ответ переключателя «Смотреть позже». Тоже только ради схемы.
    """

    is_watchlist = serializers.BooleanField(
        help_text="True — запись теперь в списке, False — убрана из него",
    )


@extend_schema_view(
    list=extend_schema(
        summary="Список фильмов и сериалов",
        description=(
            "Только опубликованные записи. Поддерживает фильтры, поиск и сортировку.\n\n"
            "Поля описания и съёмочной группы в списке не отдаются — они есть "
            "в карточке. Так список из 24 записей остаётся лёгким."
        ),
        tags=["titles"],
    ),
    retrieve=extend_schema(
        summary="Карточка фильма или сериала",
        description="Полные данные записи вместе со съёмочной группой. Черновик отдаёт `404`.",
        tags=["titles"],
    ),
)
class TitleViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Фильмы и сериалы. Только чтение: каталог ведут через админку.

    Ищем по slug, а не по номеру: адрес /api/v1/titles/nachalo-2010/
    читается человеком и совпадает с адресом страницы на сайте.
    """

    lookup_field = "slug"
    permission_classes = [permissions.AllowAny]

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, StableOrderingFilter]
    filterset_fields = ["type", "release_year", "genres__slug", "countries__slug"]
    search_fields = ["name", "original_name"]
    ordering_fields = ["release_year", "rating_average", "published_at", "name"]
    ordering = ["-release_year", "pk"]

    def get_queryset(self):
        # published() обязателен: через API черновики утекли бы наружу.
        queryset = Title.objects.published()

        # Список показывает только жанры из связанных данных (TitleListSerializer)
        # — лёгкий префетч вместо полного with_related, который тянет ещё страны,
        # студии и съёмочную группу ради карточки сайта.
        if self.action == "list":
            queryset = queryset.prefetch_related("genres")
        else:
            queryset = queryset.with_related()

        # Съёмочную группу тянем только для одной записи: в списке
        # она не нужна и стоила бы лишнего запроса.
        if self.action == "retrieve":
            queryset = queryset.with_crew()

        return queryset

    def get_serializer_class(self):
        if self.action == "retrieve":
            return TitleDetailSerializer
        return TitleListSerializer

    @extend_schema(
        summary="Поиск по каталогу",
        description=(
            "Глобальный поиск по названиям фильмов/сериалов и персонам (актёры,"
            " режиссёры). Возвращает компактные результаты для автодополнения"
            " в поисковой строке. Максимум limit записей + до 3 персон."
        ),
        parameters=[
            OpenApiParameter(name="q", type=str, required=True, description="Поисковый запрос, минимум 2 символа"),
            OpenApiParameter(name="limit", type=int, required=False, default=6, description="Максимум результатов"),
        ],
        responses=SearchResultSerializer(many=True),
        tags=["titles", "persons"],
    )
    @action(detail=False, methods=["get"])
    def search(self, request):
        q = request.query_params.get("q", "").strip()
        limit = self._parse_limit(request.query_params.get("limit"))
        results = []
        if len(q) >= 2:
            titles = (
                Title.objects.published()
                .filter(Q(name__icontains=q) | Q(original_name__icontains=q))
                .only("id", "name", "slug", "type", "release_year", "poster")
                .order_by("-release_year")[:limit]
            )
            results = [
                {
                    "id": t.id,
                    "name": t.name,
                    "slug": t.slug,
                    "type": t.type,
                    "release_year": t.release_year,
                    "poster": t.poster.url if t.poster else None,
                    "url": t.get_absolute_url(),
                }
                for t in titles
            ]
            persons = (
                Person.objects.filter(
                    Q(name__icontains=q) | Q(original_name__icontains=q)
                )
                .only("id", "name", "slug", "photo")
                .order_by("name")[:3]
            )
            for p in persons:
                results.append({
                    "id": p.id,
                    "name": p.name,
                    "slug": p.slug,
                    "type": "person",
                    "release_year": None,
                    "poster": p.photo.url if p.photo else None,
                    "url": p.get_absolute_url(),
                })
        return Response(results)

    # Значения по умолчанию и границы держим рядом с разбором,
    # чтобы схема в extend_schema и поведение не разъезжались.
    DEFAULT_SEARCH_LIMIT = 6
    MAX_SEARCH_LIMIT = 20

    @classmethod
    def _parse_limit(cls, raw_value):
        """
        Сколько подсказок вернуть.

        Параметр приходит из адресной строки, то есть это произвольный текст.
        Голый int() на «?limit=abc» поднимал ValueError и отдавал 500 — обычная
        ошибка в запросе не должна выглядеть как поломка сервера. Мусор и
        бессмысленные числа заменяем значением по умолчанию.
        """
        try:
            limit = int(raw_value)
        except (TypeError, ValueError):
            return cls.DEFAULT_SEARCH_LIMIT
        if limit < 1:
            return cls.DEFAULT_SEARCH_LIMIT
        return min(limit, cls.MAX_SEARCH_LIMIT)

    @extend_schema(
        summary="Похожие записи",
        description=(
            "Подбор по числу совпавших жанров: чем больше общих жанров, "
            "тем выше запись. Не более шести. Пагинации нет — список короткий."
        ),
        responses=TitleListSerializer(many=True),
        tags=["titles"],
    )
    @action(detail=True, methods=["get"])
    def similar(self, request, slug=None):
        titles = get_similar_titles(self.get_object())
        serializer = TitleListSerializer(titles, many=True, context=self.get_serializer_context())
        return Response(serializer.data)

    @extend_schema(
        summary="Добавить в избранное или убрать из него",
        description=(
            "Переключатель: повторный вызов убирает запись из избранного. "
            "Тело запроса не нужно. Требует авторизации."
        ),
        request=None,
        responses={
            200: OpenApiResponse(
                response=FavoriteResponseSerializer,
                description="Новое состояние записи",
                examples=[
                    OpenApiExample("Добавлено", value={"is_favorite": True}),
                    OpenApiExample("Убрано", value={"is_favorite": False}),
                ],
            ),
            403: OpenApiResponse(description="Требуется вход"),
            404: OpenApiResponse(description="Записи нет или она в черновиках"),
        },
        tags=["titles"],
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[permissions.IsAuthenticated],
    )
    def favorite(self, request, slug=None):
        # Зовёт тот же сервис, что и вьюха сайта: логика описана один раз.
        is_favorite = toggle_favorite(request.user, self.get_object())
        return Response({"is_favorite": is_favorite})

    @extend_schema(
        summary="Добавить в «Смотреть позже» или убрать из него",
        description=(
            "Переключатель: повторный вызов убирает запись из списка. "
            "Тело запроса не нужно. Требует авторизации."
        ),
        request=None,
        responses={
            200: OpenApiResponse(
                response=WatchlistResponseSerializer,
                description="Новое состояние записи",
                examples=[
                    OpenApiExample("Добавлено", value={"is_watchlist": True}),
                    OpenApiExample("Убрано", value={"is_watchlist": False}),
                ],
            ),
            403: OpenApiResponse(description="Требуется вход"),
            404: OpenApiResponse(description="Записи нет или она в черновиках"),
        },
        tags=["titles"],
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[permissions.IsAuthenticated],
    )
    def watchlist(self, request, slug=None):
        # Тот же сервис, что и у переключателя на сайте.
        is_watchlist = toggle_watchlist(request.user, self.get_object())
        return Response({"is_watchlist": is_watchlist})


class ReferenceViewSet(viewsets.ReadOnlyModelViewSet):
    """Общая основа для справочников — жанров и стран."""

    lookup_field = "slug"
    permission_classes = [permissions.AllowAny]
    pagination_class = None  # Справочники короткие, разбивать на страницы незачем.


@extend_schema_view(
    list=extend_schema(summary="Все жанры", tags=["genres"]),
    retrieve=extend_schema(summary="Жанр по адресу", tags=["genres"]),
)
class GenreViewSet(ReferenceViewSet):
    queryset = Genre.objects.all()
    serializer_class = GenreSerializer


@extend_schema_view(
    list=extend_schema(summary="Все страны", tags=["countries"]),
    retrieve=extend_schema(summary="Страна по адресу", tags=["countries"]),
)
class CountryViewSet(ReferenceViewSet):
    queryset = Country.objects.all()
    serializer_class = CountrySerializer


@extend_schema_view(
    list=extend_schema(summary="Список подборок", tags=["collections"]),
    retrieve=extend_schema(summary="Карточка подборки", tags=["collections"]),
)
class CollectionViewSet(viewsets.ReadOnlyModelViewSet):
    """Подборки."""

    lookup_field = "slug"
    permission_classes = [permissions.AllowAny]
    serializer_class = CollectionSerializer
    queryset = Collection.objects.published()

    @extend_schema(
        summary="Содержимое подборки",
        description="Записи в порядке, который задал редактор, а не по алфавиту.",
        responses=TitleListSerializer(many=True),
        tags=["collections"],
    )
    @action(detail=True, methods=["get"])
    def titles(self, request, slug=None):
        titles = Title.objects.published().with_related().in_collection(self.get_object())
        page = self.paginate_queryset(titles)
        serializer = TitleListSerializer(page, many=True, context=self.get_serializer_context())
        return self.get_paginated_response(serializer.data)


@extend_schema_view(
    list=extend_schema(
        summary="Отзывы к записи",
        description="Только прошедшие модерацию. Если запись снята с публикации — `404`.",
        tags=["reviews"],
    ),
    create=extend_schema(
        summary="Оставить отзыв",
        description=(
            "Один пользователь — один отзыв на запись. Повторный вызов вернёт `400`; "
            "чтобы изменить мнение, отредактируйте существующий отзыв через `PATCH`.\n\n"
            "Автор и запись проставляются сервером и из тела запроса не читаются."
        ),
        examples=[
            OpenApiExample(
                "Отзыв с текстом",
                value={"rating": 9, "text": "Сильная работа оператора."},
                request_only=True,
            ),
            OpenApiExample("Только оценка", value={"rating": 7}, request_only=True),
        ],
        responses={
            201: ReviewSerializer,
            400: OpenApiResponse(description="Оценка вне шкалы 1–10 или отзыв уже оставлен"),
            403: OpenApiResponse(description="Требуется вход"),
        },
        tags=["reviews"],
    ),
    update=extend_schema(summary="Заменить свой отзыв", tags=["reviews"]),
    partial_update=extend_schema(summary="Изменить свой отзыв", tags=["reviews"]),
    destroy=extend_schema(
        summary="Удалить свой отзыв",
        description="Чужой отзыв удалить нельзя — вернётся `403`.",
        tags=["reviews"],
    ),
)
class ReviewViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Отзывы к записи: /api/v1/titles/<slug>/reviews/

    RetrieveModelMixin намеренно нет: отдельный отзыв по номеру
    никому не нужен, а лишний маршрут — лишняя поверхность.
    """

    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsAuthorOrReadOnly]

    # Реальную выборку делает get_queryset. Это объявление нужно генератору
    # схемы: он определяет модель по атрибуту класса, а вызвать get_queryset
    # не может — при сборке схемы нет запроса и нет title_slug в kwargs.
    queryset = Review.objects.none()

    def get_title(self):
        """
        Запись, к которой относятся отзывы.

        Возвращает: опубликованный Title. Для черновика и несуществующего
        адреса поднимает 404.
        """
        return get_object_or_404(Title.objects.published(), slug=self.kwargs["title_slug"])

    def get_queryset(self):
        # Отбираем через get_title(), а не по title__slug: published() у отзыва
        # проверяет статус ОТЗЫВА, но не статус фильма. Без этого отзывы записи,
        # которую редактор снял с публикации, продолжали отдаваться наружу.
        return Review.objects.published().with_author().filter(title=self.get_title())

    def perform_create(self, serializer):
        # Автора и запись ставит сервер. Приди они от клиента —
        # можно было бы оставить отзыв от чужого имени.
        try:
            serializer.save(user=self.request.user, title=self.get_title())
        except IntegrityError:
            # Второй рубеж после проверки в сериализаторе. Та проверка читает
            # базу и только потом пишет, поэтому два одновременных запроса
            # проходят её оба, и второй упирается в unique_review_per_user.
            # Без этого перехвата гонка оборачивалась бы для клиента 500.
            raise serializers.ValidationError("Вы уже оставили отзыв на эту запись.")


@extend_schema(
    summary="Поставить оценку",
    description="Быстрая оценка без текста отзыва (1–10). Если оценка уже есть — обновляет.",
    request=RateRequestSerializer,
    responses={200: OpenApiResponse(description="Оценка сохранена")},
    tags=["titles"],
)
class RateTitleView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, title_slug):
        try:
            title = Title.objects.published().get(slug=title_slug)
        except Title.DoesNotExist:
            return Response({"detail": "Запись не найдена."}, status=404)

        rating = request.data.get("rating")
        if not isinstance(rating, int) or rating < 1 or rating > 10:
            return Response({"detail": "Оценка от 1 до 10."}, status=400)

        review, created = Review.objects.update_or_create(
            user=request.user,
            title=title,
            # Только оценка: defaults без text, иначе быстрая оценка
            # стирала бы текст уже оставленного отзыва.
            defaults={"rating": rating},
        )

        return Response({"rating": rating, "created": created})


@extend_schema(
    summary="Сохранить прогресс просмотра",
    description=(
        "Плеер шлёт запрос, когда пользователь начинает смотреть серию. "
        "Записывается последняя серия — карточка каталога покажет "
        "«Продолжить с S1E3». Повторный вызов перезаписывает серию."
    ),
    request=EpisodeWatchRequestSerializer,
    responses={
        200: OpenApiResponse(description="Прогресс сохранён"),
        403: OpenApiResponse(description="Требуется вход"),
        404: OpenApiResponse(description="Записи или серии нет"),
    },
    tags=["titles"],
)
class TitleWatchProgressView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, title_slug):
        try:
            title = Title.objects.published().get(slug=title_slug)
        except Title.DoesNotExist:
            return Response({"detail": "Запись не найдена."}, status=404)

        serializer = EpisodeWatchRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"detail": "Укажите номер серии."}, status=400)

        # Серия должна принадлежать именно этой записи: иначе прогресс
        # одной страницы писался бы в историю другой.
        episode = (
            Episode.objects.filter(
                pk=serializer.validated_data["episode"], title=title
            )
            .only("pk")
            .first()
        )
        if episode is None:
            return Response({"detail": "Серия не найдена."}, status=404)

        remember_episode_start(request.user, title, episode)
        return Response({"ok": True})
