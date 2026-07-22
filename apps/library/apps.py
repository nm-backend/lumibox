from django.apps import AppConfig


class LibraryConfig(AppConfig):
    """Личная библиотека: избранное и история просмотров."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.library"
    verbose_name = "Личная библиотека"
