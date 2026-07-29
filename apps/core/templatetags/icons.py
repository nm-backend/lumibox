"""
Тег для вставки SVG-иконок из спрайта.

Использование в шаблоне:
    {% load icons %}
    {% icon "home" %}
    {% icon "heart" class_name="my-class" %}
    {% icon "play" size=24 %}

Первый аргумент — имя иконки (соответствует id в icons.svg).
Остальное — опциональные HTML-атрибуты.
"""

from django import template
from django.templatetags.static import static
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def icon(name, class_name="", size=20):
    """
    Рисует SVG-иконку из спрайта.

    Принимает:
        name — идентификатор иконки в спрайте (обязательно).
        class_name — CSS-класс (опционально).
        size — размер в пикселях (по умолчанию 20).

    Возвращает:
        Строку с <svg><use href="..."/></svg>.
    """
    classes = f"icon icon--{name}"
    if class_name:
        classes += f" {class_name}"

    sprite_url = static("img/icons.svg")

    return mark_safe(
        f'<svg class="{classes}" width="{size}" height="{size}" '
        f'style="width:{size}px;height:{size}px" '
        f'aria-hidden="true" focusable="false">'
        f'<use href="{sprite_url}#icon-{name}"/>'
        f'</svg>'
    )
