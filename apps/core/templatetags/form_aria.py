"""
Связывает поле формы с его подсказкой и ошибками.

Django рендерит поле как `{{ field }}` и ничего не знает о том, что рядом
в разметке лежит текст ошибки. Пользователь скринридера слышал только
«Пароль, поле ввода»: сообщение «Пароли не совпадают» стояло следующим
абзацем, но связи с полем не имело — прочитать его можно было, только уйдя
с поля и найдя текст самому.

Фильтры дорисовывают полю aria-describedby с идентификаторами подсказки и
ошибок и, для невалидного поля, aria-invalid. Идентификаторы собираются
по той же схеме, что и в шаблоне form_fields.html — «auto_id-help» и
«auto_id-errorN».

Почему фильтром, а не в форме: разметка одна на все формы проекта, и
дописывать атрибуты в каждый виджет каждой формы значило бы держать
это знание в десятке мест.
"""

from django import template

register = template.Library()


def _describedby(field, *, with_help):
    """Собирает список идентификаторов для aria-describedby."""
    ids = []
    if with_help and field.help_text:
        ids.append(f"{field.auto_id}-help")
    for number, _error in enumerate(field.errors, start=1):
        ids.append(f"{field.auto_id}-error{number}")
    return " ".join(ids)


@register.filter
def add_error_aria(field):
    """Поле с ошибкой: помечаем недействительным и связываем с текстом ошибки."""
    attrs = {"aria-invalid": "true"}
    described = _describedby(field, with_help=True)
    if described:
        attrs["aria-describedby"] = described
    return field.as_widget(attrs=attrs)


@register.filter
def add_help_aria(field):
    """Поле без ошибок, но с подсказкой: связываем поле с подсказкой."""
    described = _describedby(field, with_help=True)
    if not described:
        return field.as_widget()
    return field.as_widget(attrs={"aria-describedby": described})
