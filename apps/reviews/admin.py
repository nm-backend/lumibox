from django.contrib import admin

from apps.catalog.models import Title
from apps.catalog.services import update_title_rating
from apps.core.cache import invalidate_for_model
from apps.reviews.models import Comment, Review


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

        # Инвалидируем кэш: batch update не шлёт сигналов
        invalidate_for_model("reviews.review")

        return updated


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    """
    Модерация обсуждений.

    Скрытый комментарий исчезает из ленты вместе со своими ответами:
    ответ без вопроса читается как обрывок разговора.
    """

    list_display = ["title", "user", "short_text", "is_reply", "status", "created_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["user__email", "user__username", "title__name", "text"]
    autocomplete_fields = ["user", "title"]
    date_hierarchy = "created_at"
    list_per_page = 50

    actions = ["hide", "publish"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "title", "parent")

    @admin.display(description="Текст")
    def short_text(self, comment):
        return comment.text[:60] + ("…" if len(comment.text) > 60 else "")

    @admin.display(description="Ответ", boolean=True)
    def is_reply(self, comment):
        return comment.parent_id is not None

    @admin.action(description="Скрыть выбранные")
    def hide(self, request, queryset):
        updated = self._change_status(queryset, Comment.Status.HIDDEN)
        self.message_user(request, f"Скрыто комментариев: {updated}")

    @admin.action(description="Опубликовать выбранные")
    def publish(self, request, queryset):
        updated = self._change_status(queryset, Comment.Status.PUBLISHED)
        self.message_user(request, f"Опубликовано комментариев: {updated}")

    def _change_status(self, queryset, status):
        """
        Меняет статус пачкой — вместе с ответами на затронутые комментарии.

        queryset.update() не шлёт сигналов, поэтому кэш сбрасываем руками:
        сайдбар «Последние комментарии» иначе продолжил бы показывать
        только что скрытое.
        """
        roots = list(queryset.values_list("pk", flat=True))
        updated = queryset.update(status=status)
        updated += Comment.objects.filter(parent_id__in=roots).exclude(status=status).update(status=status)

        invalidate_for_model("reviews.comment")
        return updated
