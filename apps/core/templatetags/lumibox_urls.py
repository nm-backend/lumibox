"""
Теги для адресов, которые обязаны быть абсолютными.

Нужны в одном месте — в <head>. Open Graph, Twitter Card и JSON-LD читают
роботы соцсетей и поисковиков: они приходят со своего сервера и относительный
путь «/static/img/og-default.png» им разрешать не от чего. Картинка предпросмотра
просто не появляется.

Отдельный тег, а не строка «{{ request.scheme }}://{{ request.get_host }}{{ ... }}»
в шаблоне, потому что адрес файла бывает уже абсолютным: с Cloudflare R2
poster.url возвращает «https://<бакет>/posters/...», и приклеенный спереди
хост сайта давал бы «https://сайт/https://бакет/...».
"""

from django import template
from django.templatetags.static import static

register = template.Library()


@register.simple_tag(takes_context=True)
def absolute_url(context, url):
    """
    Абсолютный адрес для метатегов.

    Принимает: путь («/media/posters/a.jpg») или готовый адрес
    («https://cdn/posters/a.jpg»), может принять пустую строку.
    Возвращает: адрес со схемой и хостом либо пустую строку.
    """
    if not url:
        return ""

    url = str(url)
    # Уже абсолютный (в том числе протокол-относительный «//cdn/...») —
    # отдаём как есть.
    if url.startswith(("http://", "https://", "//")):
        return url

    request = context.get("request")
    if request is None:
        # Шаблон рендерится без запроса (письмо, команда) — хоста взять неоткуда.
        return url
    return request.build_absolute_uri(url)


@register.simple_tag(takes_context=True)
def absolute_static(context, path):
    """
    То же, но для файла из статики: {% absolute_static 'img/og-default.png' %}.

    Пропускаем через static(), чтобы работала версионированная раздача
    WhiteNoise (og-default.a1b2c3.png), а затем делаем адрес абсолютным.
    """
    return absolute_url(context, static(path))
