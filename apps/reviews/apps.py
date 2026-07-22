from django.apps import AppConfig


class ReviewsConfig(AppConfig):
    """Отзывы и оценки."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reviews"
    verbose_name = "Отзывы"

    def ready(self):
        # Подключаем сигналы. Импорт именно здесь, а не в шапке файла:
        # на момент импорта apps.py модели ещё не загружены.
        from apps.reviews import signals  # noqa: F401
