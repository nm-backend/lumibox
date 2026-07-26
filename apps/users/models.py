from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse

from apps.core.validators import validate_image_file
from apps.users.managers import UserManager


class User(AbstractUser):
    """
    Пользователь MovieHub.

    Своя модель заведена сразу, до первой миграции: заменить встроенную
    модель пользователя на живом проекте очень дорого, а понадобится это
    почти наверняка — аватар, настройки, привязка к избранному.

    Логин — электронная почта. Поле username оставлено как публичное имя,
    которое видно рядом с комментариями.
    """

    email = models.EmailField("Электронная почта", unique=True)
    avatar = models.ImageField(
        "Аватар",
        upload_to="avatars/%Y/%m",
        blank=True,
        validators=[validate_image_file],
    )
    bio = models.TextField("О себе", max_length=500, blank=True)

    # Push-подписка для Web Push уведомлений.
    # Хранится как JSON строка с endpoint, keys (p256dh, auth).
    push_subscription = models.TextField("Push-подписка", blank=True, default="")

    # Входим по почте, а не по имени пользователя.
    USERNAME_FIELD = "email"

    # Поля, которые дополнительно спросит createsuperuser.
    # email сюда не входит — он уже USERNAME_FIELD.
    REQUIRED_FIELDS = ["username"]

    objects = UserManager()

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self):
        return self.username or self.email

    def get_absolute_url(self):
        return reverse("users:profile")

    @property
    def display_name(self):
        """Имя для показа: username, а если его нет — часть почты до собаки."""
        return self.username or self.email.split("@")[0]

    @property
    def initial(self):
        """Первая буква для аватара-заглушки."""
        return self.display_name[:1].upper()
