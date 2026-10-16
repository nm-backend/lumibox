from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.models import Collection, Country, Genre, Participation, Person, Title
from apps.reviews.models import Comment, Review

# Нулевой байт в тексте отсекает штатный валидатор Django: CharField получает
# ProhibitNullCharactersValidator сам, а ModelSerializer переносит валидаторы
# поля модели в поле сериализатора. Свой точно такой же валидатор здесь стоял
# раньше — защиты он не добавлял, зато клиент получал два сообщения об одной
# и той же ошибке.


class ReferenceSerializer(serializers.ModelSerializer):
    """Жанр или страна в кратком виде — для вложения в карточку записи."""

    class Meta:
        fields = ["name", "slug"]


class GenreSerializer(ReferenceSerializer):
    class Meta(ReferenceSerializer.Meta):
        model = Genre


class CountrySerializer(ReferenceSerializer):
    class Meta(ReferenceSerializer.Meta):
        model = Country


class PersonShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = Person
        fields = ["name", "slug", "photo"]


class ParticipationSerializer(serializers.ModelSerializer):
    person = PersonShortSerializer(read_only=True)
    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = Participation
        fields = ["person", "role", "role_display", "character"]


class TitleListSerializer(serializers.ModelSerializer):
    """
    Запись в списке.

    Полей меньше, чем в TitleDetailSerializer, намеренно: список из 24 карточек
    не должен тащить описание, съёмочную группу и биографии.
    """

    genres = GenreSerializer(many=True, read_only=True)
    type_display = serializers.CharField(source="get_type_display", read_only=True)
    url = serializers.CharField(source="get_absolute_url", read_only=True)

    class Meta:
        model = Title
        fields = [
            "id",
            "name",
            "slug",
            "url",
            "type",
            "type_display",
            "release_year",
            "poster",
            "age_rating",
            "rating_average",
            "rating_count",
            "genres",
        ]


class TitleDetailSerializer(TitleListSerializer):
    """Полная карточка записи."""

    countries = CountrySerializer(many=True, read_only=True)
    participations = ParticipationSerializer(many=True, read_only=True)

    class Meta(TitleListSerializer.Meta):
        fields = TitleListSerializer.Meta.fields + [
            "original_name",
            "description",
            "duration_minutes",
            "trailer_url",
            "countries",
            "participations",
            "published_at",
        ]


class CollectionSerializer(serializers.ModelSerializer):
    url = serializers.CharField(source="get_absolute_url", read_only=True)

    class Meta:
        model = Collection
        fields = ["id", "name", "slug", "url", "description", "cover"]


class ReviewSerializer(serializers.ModelSerializer):
    """
    Отзыв.

    Автор и запись проставляются на сервере, а не приходят от клиента:
    иначе можно было бы оставить отзыв от чужого имени.
    """

    author = serializers.CharField(source="user.display_name", read_only=True)
    title_slug = serializers.SlugRelatedField(
        source="title",
        slug_field="slug",
        read_only=True,
    )

    def validate(self, attrs):
        """
        Не даёт оставить второй отзыв на одну и ту же запись.

        Ограничение unique_review_per_user есть в базе, но до этой проверки
        оно срабатывало уже на INSERT: DRF отдавал не 400, а IntegrityError
        и 500. Правило про «один отзыв на запись» пользователь должен
        получать ответом формы, а не падением сервера.

        Только при создании: у существующего отзыва instance заполнен,
        и повторная проверка запретила бы автору править собственный отзыв.
        """
        if self.instance is None:
            title = self.context["view"].get_title()
            already_reviewed = Review.objects.filter(
                user=self.context["request"].user,
                title=title,
            ).exists()
            if already_reviewed:
                raise serializers.ValidationError("Вы уже оставили отзыв на эту запись.")

        return attrs

    class Meta:
        model = Review
        fields = ["id", "author", "title_slug", "rating", "text", "created_at"]
        read_only_fields = ["id", "author", "title_slug", "created_at"]


class StrictIntegerField(serializers.IntegerField):
    """JSON-целое без неявного преобразования строк и bool."""

    default_error_messages = {"invalid": "Ожидалось целое число."}

    def to_internal_value(self, data):
        # bool — подкласс int в Python, но JSON true не является оценкой 1.
        if type(data) is not int:
            self.fail("invalid")
        return super().to_internal_value(data)


class BigIntPkField(serializers.IntegerField):
    """
    Номер связанной записи в пределах bigint.

    Пара min_value/max_value у pk_field не работает: у PrimaryKeyRelatedField
    DRF вызывает pk_field.to_internal_value, минуя run_validation, — то есть
    валидаторы диапазона не запускаются вообще. Слова «не больше 2**63-1»
    в описании поля оставались обещанием: 30-значный номер уходил в запрос
    к базе, и PostgreSQL отвечал «value out of range for type bigint», а
    клиент получал 500 вместо 400. Поэтому диапазон проверяем здесь.
    """

    default_error_messages = {
        "invalid": "Ожидалось целое число.",
        "out_of_range": "Номер вне допустимого диапазона.",
    }

    def to_internal_value(self, data):
        # bool — подкласс int, но JSON true не является номером комментария.
        if isinstance(data, bool):
            self.fail("invalid")
        value = super().to_internal_value(data)
        if not 1 <= value <= 2**63 - 1:
            self.fail("out_of_range")
        return value


class RateRequestSerializer(serializers.Serializer):
    rating = StrictIntegerField(min_value=1, max_value=10)


class CommentSerializer(serializers.ModelSerializer):
    """
    Комментарий с ответами.

    Автора и запись проставляет сервер. parent приходит от клиента, но
    вьюха сверяет его с записью и схлопывает ответ на ответ: глубина
    ленты ровно два уровня.
    """

    author = serializers.CharField(source="user.display_name", read_only=True)
    replies = serializers.SerializerMethodField()

    # Номер родителя уходит в запрос к базе, поэтому диапазон ограничен
    # здесь: число больше bigint роняет запрос (и SQLite, и PostgreSQL),
    # и клиент получил бы 500 вместо 400.
    parent = serializers.PrimaryKeyRelatedField(
        queryset=Comment.objects.all(),
        required=False,
        allow_null=True,
        pk_field=BigIntPkField(),
        error_messages={
            # Текст по умолчанию рассказывает про «первичный ключ» — это
            # внутреннее устройство, клиенту нужен номер комментария.
            "does_not_exist": "Комментарий с таким номером не найден.",
            "incorrect_type": "Ожидался номер комментария.",
        },
    )

    class Meta:
        model = Comment
        fields = ["id", "author", "parent", "text", "created_at", "replies"]
        read_only_fields = ["id", "author", "created_at", "replies"]

    def validate_parent(self, parent):
        """Родитель должен быть видимым комментарием той же записи."""
        if parent is None:
            return None
        title = self.context["view"].get_title()
        if parent.title_id != title.pk:
            raise serializers.ValidationError(
                "Нельзя ответить на комментарий другой записи."
            )
        if parent.status != Comment.Status.PUBLISHED:
            raise serializers.ValidationError("Нельзя ответить на скрытый комментарий.")
        return parent

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_replies(self, comment):
        """Ответы отдаём только у корневых: у ответа их по определению нет."""
        replies = getattr(comment, "visible_replies", None)
        if not replies:
            return []
        return [
            {
                "id": reply.pk,
                "author": reply.user.display_name,
                "text": reply.text,
                "created_at": reply.created_at,
            }
            for reply in replies
        ]
