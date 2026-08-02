"""Фильтры шаблонов каталога для главной страницы в стиле Kinogo."""

from datetime import timedelta

from django import template
from django.utils import timezone
from django.utils.translation import gettext

register = template.Library()


@register.filter
def kg_posted(value):
    """Относительная дата публикации как на Kinogo: «Сегодня, 14:05»,
    «Вчера, 22:31», для более старых записей — «31.07.2026, 20:33»."""
    if not value:
        return ""
    now = timezone.localtime(timezone.now())
    local = timezone.localtime(value)
    day = local.date()
    if day == now.date():
        label = gettext("Сегодня")
    elif day == now.date() - timedelta(days=1):
        label = gettext("Вчера")
    else:
        label = local.strftime("%d.%m.%Y")
    return f"{label}, {local.strftime('%H:%M')}"


@register.filter
def kg_crew(value, role):
    """Список имён съёмочной группы по роли: режиссёр, актёры и т.д.

    value — Title, role — строка-роль Participation.Role. Возвращает
    строку «Имя / Имя», ограниченную пятью именами, из prefetch'а
    participations — без новых запросов к базе."""
    if not value:
        return ""
    participations = getattr(value, "participations", None)
    if participations is None:
        return ""
    names = [
        p.person.name
        for p in participations.all()
        if p.role == role
    ]
    if not names:
        return ""
    return " / ".join(names[:5])
