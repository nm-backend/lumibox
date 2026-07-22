"""
Здоровье контента: чего не хватает каталогу, чтобы витрина не выглядела пустой.

Каталогом управляет контент-менеджер через админку, а не разработчик. Ему нужен
простой отчёт «где дыры»: какие фильмы без постера, без фона, без описания.
Пустой постер в сетке — это серая заглушка, и десяток таких подряд создаёт
впечатление недоделанного сайта.

Запуск:  docker compose exec web python scripts/data_health.py
"""

import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from apps.catalog.models import Collection, Person, Title  # noqa: E402


def report():
    published = Title.objects.published()
    total = Title.objects.count()

    print(f"Записей всего: {total}, опубликовано: {published.count()}")
    print(f"Персон: {Person.objects.count()}")
    print(f"Подборок: {Collection.objects.count()} (опубликовано: {Collection.objects.published().count()})")
    print()

    checks = [
        ("без постера", published.filter(poster="")),
        ("без фона (backdrop)", published.filter(backdrop="")),
        ("без короткого описания", published.filter(short_description="")),
        ("без описания", published.filter(description="")),
        ("без жанров", published.filter(genres__isnull=True)),
        ("без съёмочной группы", published.filter(participations__isnull=True)),
        ("без оценки", published.filter(rating_count=0)),
    ]

    for label, queryset in checks:
        # distinct() обязателен: фильтр по m2m (жанры, участия) размножает строки.
        count = queryset.distinct().count()
        mark = "OK " if count == 0 else "— "
        print(f"  {mark} {label}: {count}")


if __name__ == "__main__":
    report()
