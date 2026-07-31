from django.contrib import admin

from apps.library.models import Favorite, WatchHistory, Watchlist


class UserTitleAdmin(admin.ModelAdmin):
    """Общая админка для избранного и истории — устроены одинаково."""

    list_display = ["user", "title", "created_at"]
    search_fields = ["user__email", "user__username", "title__name"]
    autocomplete_fields = ["user", "title"]
    date_hierarchy = "created_at"

    def get_queryset(self, request):
        # Список показывает пользователя и запись — берём их одним запросом.
        return super().get_queryset(request).select_related("user", "title")


@admin.register(Favorite)
class FavoriteAdmin(UserTitleAdmin):
    pass


@admin.register(WatchHistory)
class WatchHistoryAdmin(UserTitleAdmin):
    list_display = ["user", "title", "watched_at"]
    date_hierarchy = "watched_at"


@admin.register(Watchlist)
class WatchlistAdmin(UserTitleAdmin):
    pass
