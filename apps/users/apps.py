from django.apps import AppConfig


class UsersConfig(AppConfig):
    """Пользователи: регистрация, вход, профиль."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.users"
    verbose_name = "Пользователи"
