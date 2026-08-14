"""
Разбор ссылок YouTube для плеера MVP.

Единственное место, где адрес видео превращается в ссылку для iframe.
Правило одно: плеер открывает ТОЛЬКО YouTube, а значит и разрешаем
только его домены — youtube.com, youtu.be и их поддомены. Всё остальное
(произвольные iframe, чужие домены, javascript: и прочее) не проходит
здесь и не попадает в разметку.

Из ссылки извлекается только ID видео — строка из 11 символов
[A-Za-z0-9_-]. Плеер собирается из этого ID бэкендом, а не вставляется
сырой строкой из админки: ввести «iframe HTML» или XSS-полезную нагрузку
вместо ссылки не выйдет — парсер просто не вернёт ID.

Поддерживаемые форматы (минимум по ТЗ):
    https://www.youtube.com/watch?v=VIDEO_ID
    https://youtu.be/VIDEO_ID
    https://www.youtube.com/embed/VIDEO_ID

Плюс исторические /v/ и /shorts/, которые встречаются в копипастах
редакторов. Схема http тоже принимается — embed всегда собирается
по https.
"""

import re
from urllib.parse import parse_qs, urlparse

from django.core.exceptions import ValidationError

# ID ролика: ровно 11 символов из «безопасного» алфавита. YouTube генерирует
# именно такие — более короткая или «грязная» строка валидным ID не бывает,
# а заодно отсекает любой мусор, вставленный вместо ссылки.
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Домены, с которых разрешаем брать видео. Проверка с границей по точке:
# «evil-youtube.com» не считается поддоменом youtube.com.
_YOUTUBE_HOSTS = ("youtube.com", "youtu.be")


def _host_matches(host, domain):
    return host == domain or host.endswith(f".{domain}")


def _is_youtube_host(host):
    return any(_host_matches(host, domain) for domain in _YOUTUBE_HOSTS)


def parse_youtube_id(url):
    """
    ID ролика YouTube из ссылки, или None, если ссылка не подходит.

    None возвращается и для «совсем не ссылки», и для валидной ссылки
    на другой видеохостинг, и для ссылки YouTube с битым ID. Во всех
    трёх случаях плеер показывать нельзя — и везде причина одна:
    адрес не прошёл проверку.
    """
    if not url or not isinstance(url, str):
        return None

    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None

    # javascript:, data: и прочие не-web-схемы не должны дойти до iframe.
    if parsed.scheme not in {"http", "https"}:
        return None
    if not _is_youtube_host(parsed.hostname or ""):
        return None

    path = parsed.path.strip("/")

    if _host_matches(parsed.hostname or "", "youtu.be"):
        # Короткие ссылки: https://youtu.be/VIDEO_ID
        video_id = path.split("/")[0]
    elif parsed.path.startswith("/embed/"):
        # Готовая встраиваемая ссылка: /embed/VIDEO_ID
        # path уже без ведущего слэша: embed/ID
        video_id = path.split("/", 1)[1].split("/")[0]
    elif path.startswith("watch") or parsed.path == "/watch":
        # Классическая: /watch?v=VIDEO_ID (порядок параметров не важен).
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    elif path.startswith(("v/", "shorts/", "live/")):
        # Исторические форматы: /v/ID, /shorts/ID, /live/ID
        video_id = path.split("/", 1)[1].split("/")[0]
    else:
        return None

    # Шорткод m.youtube.com/watch?v=... и www.youtube.com/watch?v=...
    if not _VIDEO_ID.match(video_id):
        return None

    return video_id


def youtube_embed_url(url):
    """
    Ссылка для iframe: https://www.youtube.com/embed/VIDEO_ID или None.

    None — сигнал «плеер не показываем»: страница либо не отрисует
    встроенный ролик, либо покажет обычную кнопку-ссылку наружу.
    """
    video_id = parse_youtube_id(url)
    if not video_id:
        return None
    return f"https://www.youtube.com/embed/{video_id}"


def validate_youtube_url(value):
    """
    Django-валидатор для полей моделей и форм.

    Пустое значение пропускаем: поле необязательное, его отсутствие —
    законное состояние. Заполненное обязано быть ссылкой YouTube,
    иначе — ValidationError, который Django покажет рядом с полем.
    """
    if not value:
        return
    if parse_youtube_id(value) is None:
        raise ValidationError(
            "Укажите корректную ссылку на видео YouTube "
            "(watch, youtu.be или embed). Другие сервисы не поддерживаются."
        )
