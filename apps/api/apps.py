from django.apps import AppConfig


class ApiConfig(AppConfig):
    """REST API. Своих моделей не имеет — только представляет чужие."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.api"
    verbose_name = "API"
