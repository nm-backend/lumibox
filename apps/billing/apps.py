from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.billing"
    verbose_name = "Монетизация"

    def ready(self):
        # Импорт именно здесь: на момент импорта apps.py модели ещё не загружены.
        from apps.billing import signals  # noqa: F401
