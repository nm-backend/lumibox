"""
Клиент публичного API внешнего видеосервиса издателя.

Два семейства эндпоинтов с разной формой ответа:

- Списковые (GET /videos/links) отдают обёртку {success, data, meta} —
  их использует команда sync_video_service для сопоставления каталога.
- Detail-эндпоинты (GET /videos/kp/{id}, /videos/imdb/{id},
  /serials/kp/{id}, /serials/imdb/{id}) отдают запись напрямую, без
  обёртки. Их клиент тоже умеет: fetch_video_by_* / fetch_serial_by_*.

Ключ доступа передаётся заголовком `Authorization: Bearer {API_KEY}`.
Ключ берётся из settings.VIDEO_SERVICE_API_KEY и никогда не попадает в код.

Каталог большой (тысячи страниц), а API ограничивает частоту запросов
(429). Поэтому клиент ретраит с экспоненциальной паузой и держит
небольшую паузу между страницами.
"""

import time

import requests
from django.conf import settings
from django.utils import timezone

# Базовый адрес публичного API издателя: корень VIBIX_API_BASE_URL
# (по умолчанию https://vibix.org/api/v1) + сегмент /publisher.
VIDEO_SERVICE_API_BASE = f"{settings.VIBIX_API_BASE_URL.rstrip('/')}/publisher"

# Сериалы живут на отдельном хосте API без сегмента /publisher:
# документация указывает GET /api/v1/serials/kp|imdb/{id} (без префикса),
# и запросы к /api/v1/publisher/serials/... сервис отвечает 404.
VIDEO_SERVICE_SERIALS_API_BASE = settings.VIBIX_API_BASE_URL.rstrip("/")

# Таймаут на запрос: каталог большой, но зависнуть навсегда не должен.
REQUEST_TIMEOUT = 30

# Сколько раз повторяем запрос при 429/5xx и сетевых ошибках.
MAX_RETRIES = 6

# Пауза между страницами списка: троттлинг API, полный каталог тянется
# минуты, и вставлять сотни запросов подряд сервис не разрешает.
PAGE_DELAY = 0.35


class VideoServiceAPIError(RuntimeError):
    """Ошибка обращения к API видеосервиса: сеть, не-200, ответ с success=false."""


class VideoServiceNotFoundError(VideoServiceAPIError):
    """HTTP 404: записи нет в каталоге издателя."""


def get_vibix_api_token():
    """Возвращает актуальный API-токен с поддержкой старого имени настройки.

    Значение читается при каждом вызове, а не копируется один раз при импорте
    settings. Это важно для тестов, ротации конфигурации и постепенного
    перехода с VIDEO_SERVICE_API_KEY на официальное VIBIX_API_TOKEN.
    """
    official = getattr(settings, "VIBIX_API_TOKEN", "") or ""
    legacy = getattr(settings, "VIDEO_SERVICE_API_KEY", "") or ""
    return (official or legacy).strip()


def _retry_delay(attempt, response=None):
    """
    Пауза перед повтором запроса, в секундах.

    Уважаем заголовок Retry-After, если API его прислал, иначе — обычная
    экспоненциальная задержка. Кап в 60 секунд: дольше ждать смысла нет,
    это уже не троттлинг, а сломанный сервис.
    """
    retry_after = None
    if response is not None:
        retry_after = response.headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        return min(int(retry_after), 60)
    return min(2**attempt, 60)


def _retryable(status_code):
    """429 и 5xx — временные сбои, их можно переждать. Остальное — нет."""
    return status_code in (429, 500, 502, 503, 504)


def _request_json(api_key, path, params, base=VIDEO_SERVICE_API_BASE):
    """GET с Bearer-авторизацией и ретраями; возвращает распарсенный JSON."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                f"{base}{path}",
                params=params,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(_retry_delay(attempt))
                continue
            break

        if _retryable(response.status_code) and attempt < MAX_RETRIES - 1:
            time.sleep(_retry_delay(attempt, response))
            continue
        # 404 — штатный ответ detail-эндпоинтов на «записи нет»: отдельный
        # класс, чтобы вызывающий код мог отличить её от прочих ошибок.
        if response.status_code == 404:
            raise VideoServiceNotFoundError(f"Сервис не нашёл запись ({path})")
        if response.status_code != 200:
            raise VideoServiceAPIError(
                f"API видеосервиса вернул HTTP {response.status_code} для {path} "
                f"после {attempt + 1} попыток"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise VideoServiceAPIError(
                f"API видеосервиса вернул не-JSON ответ для {path}"
            ) from exc

    raise VideoServiceAPIError(
        f"Не удалось обратиться к API видеосервиса ({path}): {last_error}"
    )


def _get(api_key, path, params):
    """GET со списковым эндпоинтом: требует обёртку {success, data, meta}."""
    payload = _request_json(api_key, path, params)
    if not payload.get("success"):
        message = payload.get("message") or "без описания"
        raise VideoServiceAPIError(f"API видеосервиса ответил ошибкой ({path}): {message}")
    return payload


def _get_unwrapped(api_key, path, params, base=VIDEO_SERVICE_API_BASE):
    """GET с detail-эндпоинтом: запись приходит напрямую, без обёртки."""
    return _request_json(api_key, path, params, base=base)


def fetch_video_by_kp(api_key, kp_id):
    """
    Полная карточка видео по Kinopoisk ID (GET /videos/kp/{kpId}).

    В отличие от кратких записей /videos/links, здесь есть описание,
    рейтинги, жанры, озвучки и теги. Возвращает словарь видео.
    Кидает VideoServiceNotFoundError, если видео отсутствует в каталоге.
    """
    return _get_unwrapped(api_key, f"/videos/kp/{kp_id}", {})


def fetch_video_by_imdb(api_key, imdb_id):
    """
    Полная карточка видео по IMDb ID (GET /videos/imdb/{imdbId}).

    См. fetch_video_by_kp: форма ответа та же.
    """
    return _get_unwrapped(api_key, f"/videos/imdb/{imdb_id}", {})


def fetch_serial_by_kp(api_key, kp_id):
    """
    Сезоны и серии сериала по Kinopoisk ID (GET /serials/kp/{kpId}).

    Возвращает словарь {id, name, seasons}: seasons — список сезонов
    с сериями, или null, если структура сериала не разобрана.

    Эндпоинт живёт на отдельном базе без /publisher (см. константу
    VIDEO_SERVICE_SERIALS_API_BASE): под /api/v1/publisher/serials/...
    сервис отвечает 404.
    """
    return _get_unwrapped(
        api_key,
        f"/serials/kp/{kp_id}",
        {},
        base=VIDEO_SERVICE_SERIALS_API_BASE,
    )


def fetch_serial_by_imdb(api_key, imdb_id):
    """
    Сезоны и серии сериала по IMDb ID (GET /serials/imdb/{imdbId}).

    Та же оговорка о базе, что и у fetch_serial_by_kp: префикс /publisher
    здесь не нужен.
    """
    return _get_unwrapped(
        api_key,
        f"/serials/imdb/{imdb_id}",
        {},
        base=VIDEO_SERVICE_SERIALS_API_BASE,
    )


def fetch_video_links(api_key, *, page=1, limit=100, updated_from=None, years=None):
    """
    Одна страница списка видео.

    Возвращает (data, meta): data — массив записей, meta — объект пагинации
    (total, last_page, ...). Формат даты updated_from — как в примере
    документации: 2026-06-28T14:30:00, без микросекунд и смещения.

    years — набор годов для фильтра `year[]`: API вернёт только видео
    этих лет. Полезно, когда известен год записи каталога: не нужно
    обходить весь список в десятки тысяч записей. None — без фильтра.
    """
    params = {"page": page, "limit": limit}
    if updated_from is not None:
        params["updated_from"] = timezone.localtime(updated_from).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
    if years:
        # Список по одному ключу requests кодирует как year[]=2010&year[]=2014
        # — ровно то, что ждёт Laravel-обработчик параметра на стороне API.
        params["year[]"] = sorted(set(years))
    payload = _get(api_key, "/videos/links", params)
    return payload.get("data") or [], payload.get("meta") or {}


def fetch_video_kpids(api_key, *, content_type=None, year=None, page=1, limit=1000):
    """
    Список Kinopoisk ID загруженных видео (GET /videos/get_kpids).

    Компактнее, чем /videos/links: вместо полных записей — только ID,
    поэтому лимит по умолчанию у API больше (1000). Год принимает одно
    число (не массив), content_type — "movie" или "serial".
    Возвращает массив целых чисел.
    """
    params = {"page": page, "limit": limit}
    if content_type is not None:
        params["type"] = content_type
    if year is not None:
        params["year"] = year
    payload = _get(api_key, "/videos/get_kpids", params)
    return payload.get("data") or []


def fetch_categories(api_key):
    """Список категорий (GET /videos/categories): массив {id, name}."""
    payload = _get(api_key, "/videos/categories", {})
    return payload.get("data") or []


def fetch_genres(api_key):
    """Список жанров (GET /videos/genres): массив {id, name, name_eng}."""
    payload = _get(api_key, "/videos/genres", {})
    return payload.get("data") or []


def fetch_countries(api_key):
    """Список стран (GET /videos/countries): массив {id, name, name_eng, code}."""
    payload = _get(api_key, "/videos/countries", {})
    return payload.get("data") or []


def fetch_tags(api_key):
    """Список тегов (GET /videos/tags): массив {id, name, code}."""
    payload = _get(api_key, "/videos/tags", {})
    return payload.get("data") or []


def fetch_voiceovers(api_key):
    """Список озвучек (GET /videos/voiceovers): массив {id, name}.

    Нужен команде sync_voiceovers: сопоставление озвучек каталога
    с озвучками сервиса идёт по названию, а этот список даёт их ID.
    """
    payload = _get(api_key, "/videos/voiceovers", {})
    return payload.get("data") or []


def iter_video_links(api_key, *, limit=100, updated_from=None, years=None, max_pages=None):
    """
    Генератор по всем страницам списка видео.

    Пагинация по полю meta.last_page: API отдаёт его в каждой странице,
    поэтому заранее знать число записей не нужно. max_pages — страховка
    для отладки, чтобы не тянуть весь каталог. Между страницами — пауза,
    чтобы не упереться в троттлинг API.

    years — пробрасывается в year[] фильтр каждой страницы (см. выше).
    """
    page = 1
    while True:
        data, meta = fetch_video_links(
            api_key, page=page, limit=limit, updated_from=updated_from, years=years
        )
        yield from data
        last_page = meta.get("last_page") or page
        if page >= last_page:
            return
        if max_pages is not None and page >= max_pages:
            return
        page += 1
        time.sleep(PAGE_DELAY)
