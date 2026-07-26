from django.contrib import admin
from django.db.models import Count
from django.utils import timezone
from django.utils.html import format_html

from apps.catalog.models import (
    Award,
    Collection,
    CollectionItem,
    Country,
    Frame,
    Genre,
    Participation,
    Person,
    Studio,
    Title,
    TitleAward,
)
from apps.catalog.services import clear_home_cache


class ReferenceAdmin(admin.ModelAdmin):
    """
    Общие настройки админки для справочников — жанров и стран.

    Настройки у них одинаковые, поэтому описываем один раз.
    """

    list_display = ["name", "slug", "titles_count"]
    search_fields = ["name"]
    ordering = ["name"]

    # Django сам подставит slug из названия прямо в браузере
    # и заодно переведёт кириллицу в латиницу. Своего JavaScript не нужно.
    prepopulated_fields = {"slug": ["name"]}

    def get_queryset(self, request):
        # Считаем количество фильмов одним общим запросом.
        # Без annotate список из 20 жанров сделал бы 20 отдельных запросов.
        return super().get_queryset(request).annotate(_titles_count=Count("titles"))

    @admin.display(description="Фильмов и сериалов", ordering="_titles_count")
    def titles_count(self, reference):
        return reference._titles_count


@admin.register(Genre)
class GenreAdmin(ReferenceAdmin):
    pass


@admin.register(Country)
class CountryAdmin(ReferenceAdmin):
    pass


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    """Актёры, режиссёры и остальная съёмочная группа."""

    list_display = ["name", "original_name", "birth_date", "titles_count"]
    search_fields = ["name", "original_name"]
    ordering = ["name"]
    prepopulated_fields = {"slug": ["name"]}
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_titles_count=Count("titles", distinct=True))

    @admin.display(description="Проектов", ordering="_titles_count")
    def titles_count(self, person):
        return person._titles_count


class ParticipationInline(admin.TabularInline):
    """
    Съёмочная группа прямо на странице фильма.

    Редактору незачем ходить в отдельный раздел: роли заполняются
    там же, где и остальные данные о фильме.
    """

    model = Participation
    extra = 1
    autocomplete_fields = ["person"]
    fields = ["person", "role", "character", "order"]


class FrameInline(admin.TabularInline):
    """
    Галерея кадров прямо на странице фильма.

    Порядок задаётся числом, а не перетаскиванием: drag & drop в админке
    Django требует стороннего пакета и своего JavaScript, а поле «Порядок»
    решает ту же задачу штатными средствами.
    """

    model = Frame
    extra = 1
    fields = ["image", "frame_preview", "caption", "order"]
    readonly_fields = ["frame_preview"]

    @admin.display(description="Просмотр")
    def frame_preview(self, frame):
        if not frame.image:
            return "—"
        return format_html(
            '<img src="{}" style="height: 70px; border-radius: 6px;">', frame.image.url
        )


class CollectionItemInline(admin.TabularInline):
    """Записи подборки с порядком показа."""

    model = CollectionItem
    extra = 1
    autocomplete_fields = ["title"]
    fields = ["title", "order"]


class TitleAwardInline(admin.TabularInline):
    model = TitleAward
    extra = 0
    autocomplete_fields = ["award", "person"]
    fields = ["award", "person", "year", "category", "result"]


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    """Тематические подборки — раздел 5 ТЗ."""

    list_display = ["name", "titles_count", "is_published", "is_featured", "order"]
    list_filter = ["is_published", "is_featured"]
    list_editable = ["is_published", "is_featured", "order"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}
    inlines = [CollectionItemInline]

    fieldsets = [
        (None, {"fields": ["name", "slug", "description", "cover"]}),
        ("Показ", {"fields": ["is_published", "is_featured", "order"]}),
        ("SEO", {"fields": ["meta_title", "meta_description"], "classes": ["collapse"]}),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_titles_count=Count("titles"))

    @admin.display(description="Записей", ordering="_titles_count")
    def titles_count(self, collection):
        return collection._titles_count


@admin.register(Title)
class TitleAdmin(admin.ModelAdmin):
    """Админка фильмов и сериалов — основное рабочее место редактора."""

    inlines = [ParticipationInline, FrameInline, TitleAwardInline]

    # Похожие вручную ищутся автодополнением: список из тысяч фильмов
    # в обычном multi-select нерабочий.
    autocomplete_fields = ["related_titles"]

    list_display = ["poster_thumb", "name", "type", "release_year", "status", "rating_display", "views_display"]
    list_display_links = ["poster_thumb", "name"]
    list_filter = ["status", "type", "genres", "countries", "release_year"]
    search_fields = ["name", "original_name"]
    ordering = ["-release_year", "name"]
    list_per_page = 30
    prepopulated_fields = {"slug": ["name"]}

    # Удобный выбор жанров и стран двумя списками вместо неудобного multi-select.
    filter_horizontal = ["genres", "countries", "studios"]

    readonly_fields = [
        "poster_preview",
        "backdrop_preview",
        "logo_preview",
        "rating_display",
        "created_at",
        "updated_at",
    ]

    # Группируем поля по смыслу и по шагам заполнения: сначала о чём фильм,
    # потом характеристики, потом картинки и видео, потом публикация.
    # Длинная простыня из 18 полей подряд нечитаема.
    fieldsets = [
        (
            "О фильме",
            {
                "fields": [
                    "type",
                    "name",
                    "original_name",
                    "slug",
                    "short_description",
                    "description",
                ],
                "description": "Адрес (slug) заполнится сам из названия — трогать не нужно.",
            },
        ),
        (
            "Характеристики",
            {
                "fields": [
                    "release_year",
                    "release_date",
                    "duration_minutes",
                    "age_rating",
                    "genres",
                    "countries",
                    "studios",
                    "rating_display",
                ],
            },
        ),
        (
            "Изображения",
            {
                "fields": [
                    "poster",
                    "poster_preview",
                    "backdrop",
                    "backdrop_preview",
                    "logo",
                    "logo_preview",
                ],
                "description": (
                    "Постер — вертикальная обложка карточки. Фон — широкая картинка "
                    "для шапки страницы. Логотип — название картинкой на прозрачном фоне. "
                    "Кадры добавляются ниже, отдельным блоком."
                ),
            },
        ),
        (
            "Похожие",
            {
                "fields": ["related_titles"],
                "classes": ["collapse"],
                "description": "Оставьте пустым — похожее подберётся само по совпадению жанров.",
            },
        ),
        (
            "Трейлер",
            {
                "fields": ["trailer_url", "trailer_file"],
                "description": (
                    "Заполните ОДИН вариант: либо ссылку на видеохостинг, "
                    "либо свой видеофайл. Не оба сразу."
                ),
            },
        ),
        (
            "Публикация",
            {
                "fields": ["status", "published_at"],
                "description": "Пока статус «Черновик», фильм не виден на сайте. Дата публикации проставится сама.",
            },
        ),
        (
            "SEO",
            {
                "fields": ["meta_title", "meta_description"],
                "classes": ["collapse"],
                "description": "Если оставить пустыми, метатеги соберутся из названия и описания.",
            },
        ),
        (
            "Служебное",
            {
                "fields": ["created_at", "updated_at"],
                "classes": ["collapse"],
            },
        ),
    ]

    actions = ["publish", "unpublish"]

    @admin.display(description="Постер")
    def poster_preview(self, title):
        if not title.poster:
            return "—"
        # format_html экранирует значения, поэтому подставить сюда
        # вредоносный путь к файлу не получится.
        return format_html(
            '<img src="{}" style="height: 160px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,.3);">',
            title.poster.url,
        )

    @admin.display(description="Фон")
    def backdrop_preview(self, title):
        if not title.backdrop:
            return "—"
        return format_html(
            '<img src="{}" style="width: 320px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,.3);">',
            title.backdrop.url,
        )

    @admin.display(description="Логотип")
    def logo_preview(self, title):
        if not title.logo:
            return "—"
        # Тёмная подложка: логотипы делают на прозрачном фоне,
        # и на белой странице админки белый логотип был бы невидим.
        return format_html(
            '<img src="{}" style="height: 60px; padding: 8px; '
            'background: #14161c; border-radius: 6px;">',
            title.logo.url,
        )

    @admin.display(description="Просмотры", ordering="view_count")
    def views_display(self, title):
        return title.view_count

    @admin.display(description="Рейтинг (считается из отзывов)")
    def rating_display(self, title):
        # Рейтинг не вводится руками — он усредняется из отзывов. Показываем
        # его здесь только для справки, редактировать нельзя (editable=False).
        if not title.rating_average:
            return "Пока нет оценок"
        return f"{title.rating_average} / 10 ({title.rating_count} оцен.)"

    @admin.display(description="Обложка")
    def poster_thumb(self, title):
        """Маленький постер для колонки списка."""
        if not title.poster:
            return "—"
        return format_html(
            '<img src="{}" style="height: 56px; border-radius: 4px;">', title.poster.url
        )

    @admin.action(description="Опубликовать выбранное")
    def publish(self, request, queryset):
        # Дату публикации ставим только тем, кто публикуется впервые.
        # Порядок важен: сначала находим записи без даты, потом меняем статус.
        queryset.filter(published_at__isnull=True).update(published_at=timezone.now())

        # update() работает одним запросом и НЕ вызывает Title.save(),
        # поэтому дату выше проставляем вручную.
        updated = queryset.update(status=Title.Status.PUBLISHED)

        # По той же причине не срабатывает и сигнал сброса кэша главной.
        clear_home_cache()
        self.message_user(request, f"Опубликовано записей: {updated}")

    @admin.action(description="Снять с публикации")
    def unpublish(self, request, queryset):
        # published_at не трогаем: это дата первой публикации, она остаётся фактом.
        updated = queryset.update(status=Title.Status.DRAFT)
        clear_home_cache()
        self.message_user(request, f"Снято с публикации: {updated}")


@admin.register(Studio)
class StudioAdmin(admin.ModelAdmin):
    list_display = ["name", "titles_count", "website"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}
    readonly_fields = ["created_at", "updated_at"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_titles_count=Count("titles"))

    @admin.display(description="Произведений", ordering="_titles_count")
    def titles_count(self, studio):
        return studio._titles_count


@admin.register(Award)
class AwardAdmin(admin.ModelAdmin):
    list_display = ["name", "entries_count", "website"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}
    readonly_fields = ["created_at", "updated_at"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_entries_count=Count("title_entries"))

    @admin.display(description="Номинаций", ordering="_entries_count")
    def entries_count(self, award):
        return award._entries_count


@admin.register(TitleAward)
class TitleAwardAdmin(admin.ModelAdmin):
    list_display = ["award", "title", "person", "year", "category", "result"]
    list_filter = ["award", "result", "year"]
    search_fields = ["title__name", "person__name", "category"]
    autocomplete_fields = ["award", "title", "person"]
