from django.contrib import admin
from django.db.models import Count
from django.utils import timezone
from django.utils.html import format_html

from apps.catalog.models import (
    Award,
    Collection,
    CollectionItem,
    Country,
    Episode,
    Frame,
    Franchise,
    Genre,
    Participation,
    Person,
    PlaybackSource,
    Studio,
    Title,
    TitleAward,
    VoiceOver,
)
from apps.core.cache import invalidate_for_model


def _run_vibix_sync(request, queryset, *, dry_run=False):
    """
    Синхронизирует выбранные записи с видеосервисом Vibix.

    Вызывает тот же сервис, что и команда sync_vibix --title: для сериала
    импортируются сезоны/серии, для фильма — карточка и player_id.
    Возвращает сообщение для message_user.
    """
    from apps.catalog.video_service_api import VideoServiceAPIError
    from apps.catalog.video_service_sync import sync_title

    synced = matched = not_found = errors = skipped = 0
    for title in queryset:
        if not title.kp_id.strip() and not title.imdb_id.strip():
            skipped += 1
            continue
        try:
            stats = sync_title(title, dry_run=dry_run)
        except (VideoServiceAPIError, ValueError):
            errors += 1
            continue
        synced += 1
        matched += stats["matched"]
        not_found += stats["not_found"]

    if dry_run:
        return (f"Сухой прогон: записей {synced}, совпадений {matched}, "
                f"не найдено {not_found}, ошибок {errors}, без kp/imdb {skipped}. "
                f"В базу ничего не записано.")
    return (f"Синхронизировано с Vibix: {synced} (совпадений {matched}, "
            f"не найдено {not_found}), ошибок {errors}, без kp/imdb {skipped}.")


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


@admin.register(VoiceOver)
class VoiceOverAdmin(admin.ModelAdmin):
    """
    Справочник озвучек.

    Не наследует ReferenceAdmin: тот считает фильмы через связь titles,
    которой у озвучки нет — она связана с записями через источники видео.
    search_fields обязателен: на него опирается автодополнение в инлайне
    источников.
    """

    list_display = ["name", "slug", "vibix_voiceover_id", "sources_count"]
    list_editable = ["vibix_voiceover_id"]
    search_fields = ["name"]
    ordering = ["name"]
    prepopulated_fields = {"slug": ["name"]}

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_sources_count=Count("sources"))

    @admin.display(description="Источников", ordering="_sources_count")
    def sources_count(self, voice):
        return voice._sources_count


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


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    """
    Быстрый поиск серий по каталогу.

    Обычно серии правятся инлайном на странице сериала, но когда нужная
    серия затерялась среди сотен, искать её удобнее здесь — по названию
    сериала, сезону или номеру серии.
    """

    list_display = ["title", "season_number", "episode_number", "name", "duration_minutes", "has_video"]
    list_filter = ["title__type", "season_number"]
    search_fields = ["title__name", "name"]
    autocomplete_fields = ["title"]
    list_per_page = 50

    @admin.display(description="Видео", boolean=True)
    def has_video(self, episode):
        return bool(episode.video_url)


class EpisodeInline(admin.TabularInline):
    """
    Серии сериала прямо на странице фильма.

    Поля сезона и серии задаются числами, как и порядок кадров:
    перетаскивание требует стороннего пакета, а числа решают ту же
    задачу штатными средствами. Уникальность пары «сезон + серия»
    проверяет сама база.

    Видео здесь нет: у серии бывает несколько озвучек, и все они лежат
    в «Источниках видео» — отдельным блоком ниже.
    """

    model = Episode
    extra = 0
    fields = [
        "season_number",
        "episode_number",
        "name",
        "duration_minutes",
        "video_url",
    ]


class PlaybackSourceInline(admin.TabularInline):
    """
    Источники видео записи: файлы и внешние плееры.

    Один блок на всё: и фильм целиком (серия не выбрана), и каждая серия
    со своей озвучкой. Раньше файл серии редактировался в одном месте,
    альтернативный плеер — в другом, а выбрать озвучку было негде.
    """

    model = PlaybackSource
    extra = 0
    fields = ["episode", "voice", "kind", "file", "url", "quality", "order"]
    autocomplete_fields = ["voice"]


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

    inlines = [ParticipationInline, FrameInline, TitleAwardInline, EpisodeInline, PlaybackSourceInline]

    # Похожие вручную ищутся автодополнением: список из тысяч фильмов
    # в обычном multi-select нерабочий.
    autocomplete_fields = ["related_titles", "franchise"]

    list_display = [
        "poster_thumb",
        "name",
        "original_name",
        "type",
        "release_year",
        "kp_id",
        "imdb_id",
        "quality",
        "rating_display",
        "status",
        "views_count",
        "vibix_status",
    ]
    list_display_links = ["poster_thumb", "name"]
    list_filter = ["status", "type", "quality", "genres", "countries", "release_year"]
    search_fields = ["name", "original_name", "kp_id", "imdb_id", "slug"]
    ordering = ["-release_year", "name"]
    list_per_page = 30
    date_hierarchy = "published_at"
    prepopulated_fields = {"slug": ["name"]}

    # Удобный выбор жанров и стран двумя списками вместо неудобного multi-select.
    filter_horizontal = ["genres", "countries", "studios"]

    # views_count явно добавлен: non-editable поля нельзя указывать в
    # fieldsets, пока они не объявлены readonly_fields.
    readonly_fields = [
        "poster_preview",
        "backdrop_preview",
        "logo_preview",
        "rating_display",
        "views_count",
        "created_at",
        "updated_at",
    ]

    # Группируем поля по смыслу и по шагам заполнения: сначала о чём фильм,
    # потом видео и идентификаторы, потом картинки и публикация.
    # Длинная простыня из 18 полей подряд нечитаема.
    fieldsets = [
        (
            "Основная информация",
            {
                "fields": [
                    "type",
                    "name",
                    "original_name",
                    "slug",
                    "short_description",
                    "description",
                    "release_year",
                    "release_date",
                    "age_rating",
                ],
                "description": "Адрес (slug) заполнится сам из названия — трогать не нужно.",
            },
        ),
        (
            "Видео",
            {
                "fields": [
                    "video_url",
                    "trailer_url",
                    "trailer_file",
                    "duration_minutes",
                    "quality",
                    "voice_acting",
                    "latest_episode_info",
                ],
                "description": (
                    "Полная версия фильма и трейлер — отдельные YouTube-ссылки "
                    "(watch, youtu.be или embed), они не смешиваются. Трейлер можно "
                    "задать и своим видеофайлом. Само видео сериала живёт ниже, "
                    "в блоке «Серии»."
                ),
            },
        ),
        (
            "Идентификаторы",
            {
                "fields": ["kp_id", "imdb_id", "player_id", "player_type"],
                "classes": ["collapse"],
                "description": (
                    "ID Кинопоиска и IMDb — для внешнего плеера (data-type=kp/imdb). "
                    "player_id/player_type заполняет синхронизация с видеосервисом."
                ),
            },
        ),
        (
            "Оценки",
            {
                "fields": ["rating_display", "kp_rating", "imdb_rating"],
                "description": (
                    "Внутренний рейтинг считается из отзывов автоматически. "
                    "KP/IMDb — внешние рейтинги для справки."
                ),
            },
        ),
        (
            "Категории",
            {
                "fields": ["genres", "countries", "studios", "franchise", "related_titles"],
                "description": (
                    "Франшиза — серия связанных частей, показывается блоком «Все части». "
                    "Похожие оставьте пустыми, и подбор пойдёт сам по совпадению жанров."
                ),
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
            "Публикация",
            {
                "fields": ["status", "published_at", "views_count"],
                "description": (
                    "Пока статус «Черновик», фильм не виден на сайте. Дата публикации "
                    "проставится сама, просмотры растут при открытии страницы."
                ),
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

    actions = ["publish", "unpublish", "vibix_sync", "vibix_sync_dry_run"]

    @admin.display(description="Vibix")
    def vibix_status(self, title):
        """
        Статус интеграции с Vibix для колонки списка.

        Считается из заполненных полей, в базу не ходит:
        player_id — контент сопоставлен; kp/imdb — будет сопоставлен
        ближайшим синком; ничего — интеграции пока нет.
        """
        if title.player_id:
            return format_html(
                '<span style="color:#2e7d32;">&#10003; {}</span>', title.player_id
            )
        if title.kp_id or title.imdb_id:
            return format_html(
                '<span style="color:#b26a00;">ID задан</span>'
            )
        return format_html('<span style="color:#999;">—</span>')

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

    @admin.action(description="Синхронизировать с Vibix")
    def vibix_sync(self, request, queryset):
        self.message_user(request, _run_vibix_sync(request, queryset))

    @admin.action(description="Синхронизация с Vibix (сухой прогон)")
    def vibix_sync_dry_run(self, request, queryset):
        self.message_user(request, _run_vibix_sync(request, queryset, dry_run=True))

    @admin.action(description="Опубликовать выбранное")
    def publish(self, request, queryset):
        # Дату публикации ставим только тем, кто публикуется впервые.
        # Порядок важен: сначала находим записи без даты, потом меняем статус.
        queryset.filter(published_at__isnull=True).update(published_at=timezone.now())

        # update() работает одним запросом и НЕ вызывает Title.save(),
        # поэтому дату выше проставляем вручную.
        updated = queryset.update(status=Title.Status.PUBLISHED)

        # По той же причине не срабатывает и сигнал сброса кэша главной.
        invalidate_for_model("catalog.title")
        self.message_user(request, f"Опубликовано записей: {updated}")

    @admin.action(description="Снять с публикации")
    def unpublish(self, request, queryset):
        # published_at не трогаем: это дата первой публикации, она остаётся фактом.
        updated = queryset.update(status=Title.Status.DRAFT)
        invalidate_for_model("catalog.title")
        self.message_user(request, f"Снято с публикации: {updated}")


@admin.register(Franchise)
class FranchiseAdmin(admin.ModelAdmin):
    """Франшизы. search_fields нужен автодополнению в карточке записи."""

    list_display = ["name", "titles_count"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}
    readonly_fields = ["created_at", "updated_at"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_titles_count=Count("titles"))

    @admin.display(description="Частей", ordering="_titles_count")
    def titles_count(self, franchise):
        return franchise._titles_count


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
