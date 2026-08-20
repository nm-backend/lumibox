"""
Превращение ссылки на видеохостинг во встраиваемую (embed).

Зачем отдельный модуль: правило «какой хост считается доверенным» —
это вопрос безопасности, а не вёрстки. Держать его в шаблоне значит
однажды вставить в iframe произвольный адрес, который ввёл редактор.

Работает по белому списку: узнали хост — отдаём embed-ссылку, не узнали —
возвращаем None, и страница покажет обычную кнопку со ссылкой наружу.
"""

from urllib.parse import urlparse

from apps.catalog.youtube import parse_youtube_id

# Только https: URLField пропускает и http, но встраивать незащищённый
# фрейм на https-странице бессмысленно — браузер его заблокирует.
EMBED_SCHEME = "https"


def _host_matches(host, domain):
    """
    Точное совпадение хоста или его поддомена.

    Проверяем именно так, а не host.endswith(domain): «evil-youtube.com»
    заканчивается на «youtube.com» и прошёл бы наивную проверку насквозь.
    Нужна граница по точке.
    """
    return host == domain or host.endswith(f".{domain}")


def _youtube(parsed):
    # Тот же строгий 11-символьный ID, что у основного YouTube-плеера.
    # Два разных парсера раньше расходились: video_url отклонял v=abc,
    # а PlaybackSource строил из него заведомо битый iframe.
    video_id = parse_youtube_id(parsed.geturl())
    return f"{EMBED_SCHEME}://www.youtube.com/embed/{video_id}" if video_id else None


def _vimeo(parsed):
    if not _host_matches(parsed.hostname or "", "vimeo.com"):
        return None

    video_id = parsed.path.strip("/").split("/")[0]
    # У Vimeo идентификатор всегда числовой — заодно отсекает мусор в пути.
    if not video_id.isdigit():
        return None

    return f"{EMBED_SCHEME}://player.vimeo.com/video/{video_id}"


def _rutube(parsed):
    if not _host_matches(parsed.hostname or "", "rutube.ru"):
        return None

    parts = [part for part in parsed.path.split("/") if part]
    # Формат: /video/<hash>/ и уже готовый /play/embed/<hash>
    if len(parts) >= 2 and parts[0] in {"video", "play"}:
        video_id = parts[-1]
        return f"{EMBED_SCHEME}://rutube.ru/play/embed/{video_id}"
    return None


# Порядок не важен — каждый распознаватель сам проверяет свой хост.
RESOLVERS = (_youtube, _vimeo, _rutube)


def get_embed_url(url):
    """
    Возвращает встраиваемую ссылку для известного видеохостинга.

    Принимает: адрес, введённый редактором.
    Возвращает: https-ссылку для iframe или None, если хост незнакомый
    либо адрес битый. None — это не ошибка, а сигнал показать
    обычную ссылку вместо встроенного плеера.
    """
    if not url:
        return None

    try:
        parsed = urlparse(url)
    except ValueError:
        # urlparse спотыкается, например, о битый IPv6-литерал в адресе.
        return None

    # Ни javascript:, ни data: во фрейм не попадут: пускаем только веб-схемы.
    if parsed.scheme not in {"http", "https"}:
        return None

    for resolver in RESOLVERS:
        embed_url = resolver(parsed)
        if embed_url:
            return embed_url

    return None
