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
# (по умолчанию выделенный production host https://api.vibix.org/api/v1)
# + сегмент /publisher.
VIDEO_SERVICE_API_BASE = f"{settings.VIBIX_API_BASE_URL.rstrip('/')}/publisher"

# Сериалы живут на отдельном хосте API без сегмента /publisher:
# документация указывает GET /api/v1/serials/kp|imdb/{id} (без префикса),
# и запросы к /api/v1/publisher/serials/... сервис отвечает 404.
VIDEO_SERVICE_SERIALS_API_BASE = settings.VIBIX_API_BASE_URL.rstrip("/")

# Раздельные таймауты соединения и чтения. Недоступный DNS/хост не должен
# держать воркер 30 секунд до начала ответа; объёмный JSON при этом получает
# достаточно времени на чтение.
REQUEST_TIMEOUT = (5, 30)

# Сколько раз повторяем запрос при 429/5xx и сетевых ошибках.
MAX_RETRIES = 6

# Пауза между страницами списка: троттлинг API, полный каталог тянется
# минуты, и вставлять сотни запросов подряд сервис не разрешает.
PAGE_DELAY = 0.35


class VideoServiceAPIError(RuntimeError):
    """Ошибка обращения к API видеосервиса: сеть, не-200, ответ с success=false."""


class VideoServiceNotFoundError(VideoServiceAPIError):
    """HTTP 404: записи нет в каталоге издателя."""


class VideoServiceAuthenticationError(VideoServiceAPIError):
    """Токен отсутствует, отозван или API перенаправил запрос на форму входа."""


class VideoServicePermissionError(VideoServiceAPIError):
    """HTTP 403: аккаунту недоступен запрошенный ресурс."""


class VideoServiceValidationError(VideoServiceAPIError):
    """HTTP 422: API отклонил параметры запроса."""


def login_vibix(email=None, password=None):
    """Аутентификация издателя в API Vibix (POST /api/v1/login).

    Возвращает словарь {access_token, token_type, role, id} или поднимает
    VideoServiceAuthenticationError.
    """
    email = (email or getattr(settings, "VIBIX_USERNAME", "") or "").strip()
    password = (password or getattr(settings, "VIBIX_PASSWORD", "") or "").strip()
    if not email or not password:
        raise VideoServiceAuthenticationError("VIBIX_USERNAME / VIBIX_PASSWORD не заданы")
    base_url = settings.VIBIX_API_BASE_URL.rstrip("/")
    try:
        response = requests.post(
            f"{base_url}/login",
            json={"email": email, "password": password},
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise VideoServiceAPIError("Не удалось связаться с сервером авторизации Vibix") from exc
    if response.status_code != 200:
        raise VideoServiceAuthenticationError("Неверный логин или пароль Vibix")
    try:
        data = response.json()
    except ValueError as exc:
        raise VideoServiceAPIError("Сервер авторизации Vibix вернул не-JSON ответ") from exc
    token = data.get("access_token")
    if not token:
        raise VideoServiceAuthenticationError("API Vibix не вернул access_token")
    return data


def get_vibix_api_token(auto_login=False):
    """Возвращает актуальный API-токен с поддержкой старого имени настройки.

    Значение читается при каждом вызове, а не копируется один раз при импорте
    settings. Это важно для тестов, ротации конфигурации и постепенного
    перехода с VIDEO_SERVICE_API_KEY на официальное VIBIX_API_TOKEN.
    Если токен пуст и auto_login=True, пытается получить токен через login_vibix.
    """
    official = getattr(settings, "VIBIX_API_TOKEN", "") or ""
    legacy = getattr(settings, "VIDEO_SERVICE_API_KEY", "") or ""
    token = (official or legacy).strip()
    if not token and auto_login:
        try:
            auth_data = login_vibix()
            token = auth_data.get("access_token", "").strip()
        except Exception:
            pass
    return token


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
    """GET с Bearer-авторизацией и ретраями; возвращает JSON-объект.

    Редиректы отключены намеренно. Без токена Vibix может отправить клиента
    на HTML-форму входа; requests по умолчанию следует туда, и конечный 404
    ошибочно выглядел как «видео не найдено». Авторизационная ошибка должна
    останавливать синхронизацию, а не записывать ложный not_found.
    """
    if not str(api_key or "").strip():
        raise VideoServiceAuthenticationError("VIBIX_API_TOKEN не задан")

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                f"{base}{path}",
                params=params,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(_retry_delay(attempt))
                continue
            raise VideoServiceAPIError(
                f"Не удалось обратиться к API видеосервиса ({path})"
            ) from exc

        status = response.status_code
        if _retryable(status):
            if attempt < MAX_RETRIES - 1:
                time.sleep(_retry_delay(attempt, response))
                continue
            raise VideoServiceAPIError(
                f"API видеосервиса вернул HTTP {status} для {path} "
                f"после {attempt + 1} попыток"
            )

        if status in (301, 302, 303, 307, 308):
            raise VideoServiceAuthenticationError(
                f"API видеосервиса перенаправил запрос {path}; проверьте токен и API URL"
            )
        if status == 401:
            raise VideoServiceAuthenticationError("VIBIX_API_TOKEN отклонён сервисом")
        if status == 403:
            raise VideoServicePermissionError(
                f"Аккаунту Vibix недоступен ресурс {path}"
            )
        if status == 404:
            raise VideoServiceNotFoundError(f"Сервис не нашёл запись ({path})")
        if status == 422:
            raise VideoServiceValidationError(
                f"API видеосервиса отклонил параметры запроса {path}"
            )
        if status != 200:
            raise VideoServiceAPIError(
                f"API видеосервиса вернул HTTP {status} для {path}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise VideoServiceAPIError(
                f"API видеосервиса вернул не-JSON ответ для {path}"
            ) from exc
        if not isinstance(payload, dict):
            raise VideoServiceAPIError(
                f"API видеосервиса вернул JSON не в виде объекта для {path}"
            )
        return payload

    # Недостижимая страховка для статических анализаторов: цикл либо
    # возвращает payload, либо поднимает конкретное исключение.
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


def _kinopoisk_id(value):
    value = str(value or "").strip()
    if not value.isdigit():
        raise VideoServiceValidationError("Kinopoisk ID должен состоять из цифр")
    return value


def _imdb_id(value):
    value = str(value or "").strip().lower()
    if not value.startswith("tt") or not value[2:].isdigit():
        raise VideoServiceValidationError("IMDb ID должен иметь формат tt1234567")
    return value


def fetch_video_by_kp(api_key, kp_id):
    """
    Полная карточка видео по Kinopoisk ID (GET /videos/kp/{kpId}).

    В отличие от кратких записей /videos/links, здесь есть описание,
    рейтинги, жанры, озвучки и теги. Возвращает словарь видео.
    Кидает VideoServiceNotFoundError, если видео отсутствует в каталоге.
    """
    return _get_unwrapped(api_key, f"/videos/kp/{_kinopoisk_id(kp_id)}", {})


def fetch_video_by_imdb(api_key, imdb_id):
    """
    Полная карточка видео по IMDb ID (GET /videos/imdb/{imdbId}).

    См. fetch_video_by_kp: форма ответа та же.
    """
    return _get_unwrapped(api_key, f"/videos/imdb/{_imdb_id(imdb_id)}", {})


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
        f"/serials/kp/{_kinopoisk_id(kp_id)}",
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
        f"/serials/imdb/{_imdb_id(imdb_id)}",
        {},
        base=VIDEO_SERVICE_SERIALS_API_BASE,
    )


def fetch_video_links(
    api_key,
    *,
    page=1,
    limit=100,
    updated_from=None,
    years=None,
    content_type=None,
):
    """
    Одна страница списка видео.

    Возвращает (data, meta): data — массив записей, meta — объект пагинации
    (total, last_page, ...). Формат даты updated_from — как в примере
    документации: 2026-06-28T14:30:00, без микросекунд и смещения.

    years — набор годов для фильтра `year[]`: API вернёт только видео
    этих лет. Полезно, когда известен год записи каталога: не нужно
    обходить весь список в десятки тысяч записей. None — без фильтра.

    content_type — серверный фильтр `type` ("movie" или "serial"):
    массовый импорт обходит фильмы и сериалы раздельно (серии сериалов
    тянутся отдельным этапом), и фильтр на стороне API экономит обход
    половины каталога.
    """
    valid_limits = (20, 50, 100)
    if limit not in valid_limits:
        limit = min(valid_limits, key=lambda x: abs(x - limit))
    params: dict[str, object] = {"page": page, "limit": limit}
    if content_type is not None:
        if content_type not in ("movie", "serial"):
            raise VideoServiceValidationError(
                "Фильтр type принимает только movie или serial"
            )
        params["type"] = content_type
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


def iter_video_links(
    api_key,
    *,
    limit=100,
    updated_from=None,
    years=None,
    max_pages=None,
    content_type=None,
):
    """
    Генератор по всем страницам списка видео.

    Пагинация по полю meta.last_page: API отдаёт его в каждой странице,
    поэтому заранее знать число записей не нужно. max_pages — страховка
    для отладки, чтобы не тянуть весь каталог. Между страницами — пауза,
    чтобы не упереться в троттлинг API.

    years — пробрасывается в year[] фильтр каждой страницы (см. выше).
    content_type — пробрасывается в серверный фильтр type (см. выше).
    """
    page = 1
    while True:
        data, meta = fetch_video_links(
            api_key,
            page=page,
            limit=limit,
            updated_from=updated_from,
            years=years,
            content_type=content_type,
        )
        yield from data
        last_page = meta.get("last_page") or page
        if page >= last_page:
            return
        if max_pages is not None and page >= max_pages:
            return
        page += 1
        time.sleep(PAGE_DELAY)
