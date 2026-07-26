"""
Фабрики тестовых объектов.

Собраны в одном месте, чтобы тесты не повторяли создание одних и тех же
записей. Без фабрик каждый тест начинался бы с десяти строк подготовки,
и правка модели ломала бы весь набор разом.

Своих зависимостей не тянут: обычные функции вместо factory_boy —
для проекта такого размера этого достаточно, а читать проще.
"""

import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.catalog.models import Collection, CollectionItem, Country, Genre, Participation, Person, Title
from apps.reviews.models import Review

User = get_user_model()


def make_poster(width=200, height=300, name="poster.png"):
    """Создаёт тестовое изображение-постер."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")

# Счётчик для уникальных значений. Простая замена sequence из factory_boy:
# без него второй вызов create_genre() упёрся бы в unique на slug.
_counter = {"value": 0}


def next_number():
    _counter["value"] += 1
    return _counter["value"]


def create_user(**kwargs):
    number = next_number()
    kwargs.setdefault("email", f"user{number}@example.com")
    kwargs.setdefault("username", f"user{number}")
    password = kwargs.pop("password", "very-secret-pass-123")
    return User.objects.create_user(password=password, **kwargs)


def create_genre(**kwargs):
    number = next_number()
    kwargs.setdefault("name", f"Жанр {number}")
    kwargs.setdefault("slug", f"genre-{number}")
    return Genre.objects.create(**kwargs)


def create_country(**kwargs):
    number = next_number()
    kwargs.setdefault("name", f"Страна {number}")
    kwargs.setdefault("slug", f"country-{number}")
    return Country.objects.create(**kwargs)


def create_person(**kwargs):
    number = next_number()
    kwargs.setdefault("name", f"Персона {number}")
    kwargs.setdefault("slug", f"person-{number}")
    return Person.objects.create(**kwargs)


def create_title(genres=(), countries=(), **kwargs):
    number = next_number()
    kwargs.setdefault("name", f"Фильм {number}")
    kwargs.setdefault("slug", f"title-{number}")
    kwargs.setdefault("release_year", 2020)
    kwargs.setdefault("description", "Описание для теста.")
    # По умолчанию создаём опубликованное: черновик нужен реже,
    # и его всегда можно попросить явно.
    kwargs.setdefault("status", Title.Status.PUBLISHED)

    title = Title.objects.create(**kwargs)

    if genres:
        title.genres.set(genres)
    if countries:
        title.countries.set(countries)

    return title


def create_participation(title=None, person=None, **kwargs):
    kwargs.setdefault("role", Participation.Role.ACTOR)
    return Participation.objects.create(
        title=title or create_title(),
        person=person or create_person(),
        **kwargs,
    )


def create_review(title=None, user=None, **kwargs):
    kwargs.setdefault("rating", 8)
    kwargs.setdefault("text", "Хороший фильм.")
    return Review.objects.create(
        title=title or create_title(),
        user=user or create_user(),
        **kwargs,
    )


def create_collection(titles=(), **kwargs):
    number = next_number()
    kwargs.setdefault("name", f"Подборка {number}")
    kwargs.setdefault("slug", f"collection-{number}")
    kwargs.setdefault("is_published", True)

    collection = Collection.objects.create(**kwargs)

    for order, title in enumerate(titles):
        CollectionItem.objects.create(collection=collection, title=title, order=order)

    return collection
