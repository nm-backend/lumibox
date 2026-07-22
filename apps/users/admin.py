from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.users.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Админка пользователя.

    Наследуемся от штатной UserAdmin: она умеет правильно работать
    с паролями (показывает хеш только для чтения и даёт форму смены).
    Переопределяем поля — у нас логин по почте и есть аватар.
    """

    list_display = ["email", "username", "is_staff", "is_active", "date_joined"]
    list_filter = ["is_staff", "is_superuser", "is_active"]
    search_fields = ["email", "username"]
    ordering = ["-date_joined"]

    fieldsets = [
        (None, {"fields": ["email", "password"]}),
        ("Профиль", {"fields": ["username", "bio", "avatar"]}),
        ("Права", {"fields": ["is_active", "is_staff", "is_superuser", "groups", "user_permissions"]}),
        ("Даты", {"fields": ["last_login", "date_joined"]}),
    ]

    # Форма создания пользователя в админке: логин — почта.
    add_fieldsets = [
        (
            None,
            {
                "classes": ["wide"],
                "fields": ["email", "username", "password1", "password2"],
            },
        ),
    ]
