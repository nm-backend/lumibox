from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import BaseUserManager


class UserManager(BaseUserManager):
    """
    Менеджер пользователей, где логин — электронная почта.

    Стандартный менеджер Django ждёт первым аргументом username.
    Раз мы сделали логином email, нужен свой: иначе сломается
    команда createsuperuser.
    """

    # Позволяет ссылаться на менеджер из миграций.
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Электронная почта обязательна")

        email = self.normalize_email(email)
        # Приводим весь адрес к нижнему регистру, а не только домен:
        # вход на сайте принимает email без учёта регистра (forms.py
        # приводит к lower), а нормализация Django трогает лишь домен.
        # Иначе пользователь, созданный из админки через createsuperuser
        # с «Vasya@mail.ru», никогда не смог бы войти.
        email = email.lower()
        user = self.model(email=email, **extra_fields)

        # make_password хеширует пароль. В базу открытый текст не попадает никогда.
        user.password = make_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        # Проверяем явно: молча создать «суперпользователя» без прав нельзя.
        if extra_fields.get("is_staff") is not True:
            raise ValueError("У суперпользователя is_staff должно быть True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("У суперпользователя is_superuser должно быть True")

        return self._create_user(email, password, **extra_fields)
