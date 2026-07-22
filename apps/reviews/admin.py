from django.contrib import admin

from apps.catalog.models import Title
from apps.catalog.services import update_title_rating
from apps.reviews.models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    """Модерация отзывов — раздел 5 ТЗ."""

    list_display = ["title", "user", "rating", "status", "created_at"]
    list_filter = ["status", "rating", "created_at"]
    search_fields = ["user__email", "user__username", "title__name", "text"]
    autocomplete_fields = ["user", "title"]
    date_hierarchy = "created_at"
    list_per_page = 50

    actions = ["hide", "publish"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "title")

    @admin.action(description="Скрыть выбранные")
    def hide(self, request, queryset):
        updated = self._change_status(queryset, Review.Status.HIDDEN)
        self.message_user(request, f"Скрыто отзывов: {updated}")

    @admin.action(description="Опубликовать выбранные")
    def publish(self, request, queryset):
        updated = self._change_status(queryset, Review.Status.PUBLISHED)
        self.message_user(request, f"Опубликовано отзывов: {updated}")

    def _change_status(self, queryset, status):
        """
        Меняет статус пачкой и пересчитывает рейтинг затронутых записей.

        queryset.update() работает одним запросом и НЕ шлёт сигнал post_save,
        поэтому рейтинг сам не обновится. Собираем номера записей заранее:
        после update() выборка уже не найдёт то, что искала.
        """
        title_ids = list(queryset.values_list("title_id", flat=True).distinct())
        updated = queryset.update(status=status)

        for title in Title.objects.filter(pk__in=title_ids):
            update_title_rating(title)

        return updated
