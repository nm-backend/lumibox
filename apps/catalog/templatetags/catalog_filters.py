"""Фильтры шаблонов каталога для главной страницы."""

import functools
from datetime import timedelta

from django import template
from django.utils import timezone
from django.utils.translation import gettext

register = template.Library()


@functools.lru_cache(maxsize=1024)
def _has_webp(storage, name: str) -> bool:
    """Проверяет существование WebP-копии рядом с оригиналом.

    Кэшируется по имени файла: на странице каталога 17 постеров, и без
    кэша каждый рендер делал бы по два похода в storage на карточку.
    """
    if not name:
        return False
    base, _ = name.rsplit(".", 1) if "." in name else (name, "")
    try:
        return storage.exists(f"{base}.webp")
    except (OSError, NotImplementedError):
        return False


@register.filter
def webp_url(value):
    """URL WebP-версии изображения, если она существует, иначе оригинал.

    WebP-копии создаются сигналом при сохранении (apps.catalog.webp),
    весят в ~3 раза меньше JPG. Использование: {{ title.poster|webp_url }}.
    Ожидает ImageFieldFile; безопасен для пустых полей.
    """
    if not value or not getattr(value, "name", None):
        return ""
    if _has_webp(value.storage, value.name):
        base, _ = value.name.rsplit(".", 1)
        return value.storage.url(f"{base}.webp")
    return value.url


@register.filter
def lb_posted(value):
    """Относительная дата публикации: «Сегодня, 14:05»,
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
def ru_plural(value, forms):
    """Русские плюральные формы: «1 произведение, 2 произведения, 5 произведений».

    forms — три формы через запятую: "произведение,произведения,произведений".
    Стандартный фильтр pluralize в Django 5.2 поддерживает только две формы,
    поэтому для русского нужен свой: правило — 1 (но не 11) → первая форма,
    2–4 (но не 12–14) → вторая, остальное → третья.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return forms.split(",")[-1]
    one, few, many = forms.split(",")
    n10 = n % 10
    n100 = n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return few
    return many


@register.filter
def lb_crew(value, role):
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
