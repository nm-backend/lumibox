from django.apps import AppConfig


class CatalogConfig(AppConfig):
    """Каталог: фильмы, сериалы и справочники к ним."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalog"
    verbose_name = "Каталог"

    def ready(self):
        # Импорт именно здесь: на момент импорта apps.py модели ещё не загружены.
        from apps.catalog import signals  # noqa: F401
        # WebP-конвертация: при загрузке постера/фона/логотипа
        # создаёт WebP-копию рядом с оригиналом.
        from apps.catalog import webp  # noqa: F401
