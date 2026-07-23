from django.contrib import admin

from apps.streaming.models import Episode, PlaybackPreference, Season, SubtitleTrack, VideoAsset, WatchProgress


class EpisodeInline(admin.TabularInline):
    model = Episode
    extra = 0
    fields = ["number", "name", "duration_seconds", "is_published"]
    ordering = ["number"]


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ["title", "number", "display_name", "release_year", "is_published"]
    list_filter = ["is_published", "release_year"]
    search_fields = ["title__name", "name"]
    autocomplete_fields = ["title"]
    inlines = [EpisodeInline]

    @admin.display(description="Название")
    def display_name(self, season):
        return season.display_name


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ["season", "number", "name", "duration_seconds", "is_published"]
    list_filter = ["is_published", "season__title"]
    search_fields = ["name", "season__title__name"]
    autocomplete_fields = ["season"]
    ordering = ["season__title", "season__number", "number"]


class SubtitleTrackInline(admin.TabularInline):
    model = SubtitleTrack
    extra = 0
    fields = ["language_code", "label", "kind", "is_default", "storage_key", "subtitle_file"]


@admin.register(VideoAsset)
class VideoAssetAdmin(admin.ModelAdmin):
    list_display = ["content_label", "provider", "stream_type", "status", "access_level", "allow_download"]
    list_filter = ["provider", "stream_type", "status", "access_level", "allow_download"]
    search_fields = ["title__name", "episode__name", "episode__season__title__name", "asset_key"]
    autocomplete_fields = ["title", "episode"]
    readonly_fields = ["id", "created_at", "updated_at"]
    inlines = [SubtitleTrackInline]
    fieldsets = [
        ("Контент", {"fields": ["title", "episode"]}),
        ("Доставка", {"fields": ["provider", "stream_type",            "asset_key", "media_file", "duration_seconds",
            "available_qualities",
        ]}),
        ("Лицензия и доступ", {"fields": ["status", "access_level", "license_ends_at"]}),
        ("Офлайн", {"fields": ["allow_download", "download_name"]}),
        ("Служебное", {"fields": ["id", "created_at", "updated_at"]}),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("title", "episode__season__title")

    @admin.display(description="Контент")
    def content_label(self, asset):
        return str(asset.content)


@admin.register(PlaybackPreference)
class PlaybackPreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "autoplay_next", "default_quality", "default_speed", "subtitles_language"]
    search_fields = ["user__email", "user__username"]
    autocomplete_fields = ["user"]


@admin.register(WatchProgress)
class WatchProgressAdmin(admin.ModelAdmin):
    list_display = ["user", "video_asset", "position_seconds", "duration_seconds", "is_completed", "last_watched_at"]
    list_filter = ["is_completed", "last_watched_at"]
    search_fields = ["user__email", "user__username", "video_asset__title__name"]
    autocomplete_fields = ["user", "video_asset"]
    readonly_fields = ["created_at", "updated_at", "last_watched_at"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("user", "video_asset__title", "video_asset__episode__season__title")
        )
