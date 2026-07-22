from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Приложение с общим кодом, который используют все остальные."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Общее"
