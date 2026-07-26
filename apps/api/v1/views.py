from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema, extend_schema_view
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
    SeasonSerializer,
    TitleDetailSerializer,
    TitleListSerializer,
)
from apps.catalog.models import Collection, Country, Genre, Title
from apps.catalog.services import get_similar_titles
from apps.core.search import suggest_corrections
from apps.library.services import toggle_favorite
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
        if ordering and "pk" not in ordering and "-pk" not in ordering:
            return [*ordering, "pk"]
        return ordering


class FavoriteResponseSerializer(serializers.Serializer):
    """
    Ответ переключателя избранного.

    Существует только ради схемы: сама вьюха отдаёт обычный словарь,
    и без этого класса в документации на его месте была бы пустота.
    """

    is_favorite = serializers.BooleanField(
        help_text="True — запись теперь в избранном, False — убрана из него",
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
        queryset = Title.objects.published().with_related()

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
        summary="Сезоны и серии сериала",
        description="Возвращает сезоны с эпизодами. Только для сериалов. Для фильмов — пустой список.",
        responses=SeasonSerializer(many=True),
        tags=["titles"],
    )
    @action(detail=True, methods=["get"])
    def seasons(self, request, slug=None):
        title = self.get_object()
        seasons = title.seasons.filter(is_published=True).prefetch_related("episodes").order_by("number")
        serializer = SeasonSerializer(seasons, many=True)
        return Response(serializer.data)


class SearchAutocompleteView(APIView):
    """Автокомплит поиска: возвращает подсказки по мере ввода."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = []  # Отдельный throttle для автокомплита

    def get(self, request):
        query = request.GET.get("q", "").strip()
        if len(query) < 2:
            return Response({"suggestions": [], "corrections": []})

        titles = (
            Title.objects.published()
            .filter(Q(name__icontains=query) | Q(original_name__icontains=query))
            .values("name", "slug", "release_year", "type")[:8]
        )

        suggestions = [
            {
                "name": t["name"],
                "slug": t["slug"],
                "year": t["release_year"],
                "type": t["type"],
                "url": f"/title/{t['slug']}/",
            }
            for t in titles
        ]

        # Если мало результатов — предлагаем исправления
        corrections = []
        if len(suggestions) < 3:
            all_titles = list(
                Title.objects.published().values_list("name", flat=True)[:500]
            )
            corrections = suggest_corrections(query, all_titles, max_suggestions=3)

        return Response({"suggestions": suggestions, "corrections": corrections})


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
