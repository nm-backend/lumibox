"""
Быстрая проверка живых страниц: открывается ли всё главное после изменений.

Не заменяет тесты — они проверяют поведение. Здесь другая задача: убедиться,
что реальные URL отдают 200 на реальных данных базы. Ровно на этом стыке
ломались вещи, которые тесты не ловили: забытый инлайн в админке,
опечатка в шаблоне, отвалившийся роут.

Запуск:  docker compose exec web python scripts/smoke_pages.py
"""

import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402

from apps.catalog.models import Collection, Person, Title  # noqa: E402


def build_checks():
    """Собирает список (url, подпись) из того, что реально есть в базе."""
    checks = [
        ("/", "главная"),
        ("/catalog/", "каталог"),
        ("/catalog/?q=а", "каталог: поиск"),
        ("/catalog/?type=movie", "каталог: фильтр"),
        ("/collections/", "подборки"),
        ("/api/v1/titles/", "API: список"),
        ("/api/docs/", "Swagger"),
        ("/api/redoc/", "ReDoc"),
        ("/api/schema/", "схема OpenAPI"),
        ("/sitemap.xml", "карта сайта"),
        ("/admin/", "админка: корень"),
        ("/admin/catalog/title/", "админка: список фильмов"),
        ("/admin/catalog/title/add/", "админка: добавить фильм"),
    ]

    title = Title.objects.published().first()
    if title:
        checks.append((title.get_absolute_url(), f"фильм: {title.name}"))
        checks.append((f"/admin/catalog/title/{title.pk}/change/", "админка: правка фильма"))
        checks.append((f"/api/v1/titles/{title.slug}/", "API: карточка"))

    person = Person.objects.first()
    if person:
        checks.append((person.get_absolute_url(), f"персона: {person.name}"))

    collection = Collection.objects.published().first()
    if collection:
        checks.append((collection.get_absolute_url(), f"подборка: {collection.name}"))

    return checks


def main():
    admin = get_user_model().objects.filter(is_superuser=True).first()
    if admin is None:
        print("Нет суперпользователя — админку проверить не получится.")
        return 1

    # SERVER_NAME обязателен: по умолчанию тестовый клиент представляется
    # хостом «testserver», который вне тестов не входит в ALLOWED_HOSTS,
    # и все страницы отвечали бы 400 — не из-за поломки, а из-за проверки.
    client = Client(SERVER_NAME="localhost")
    client.force_login(admin)

    failures = []
    for url, label in build_checks():
        response = client.get(url, follow=True)
        mark = "OK " if response.status_code == 200 else "БЕДА"
        print(f"  {mark} {response.status_code}  {label}  ({url})")
        if response.status_code != 200:
            failures.append((url, label, response.status_code))

    print()
    if failures:
        print(f"Проблемных страниц: {len(failures)}")
        return 1

    print("Все страницы отвечают 200.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
