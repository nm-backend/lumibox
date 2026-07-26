import logging
import time

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.views.static import serve

from apps.core.cache import get_cache_version

logger = logging.getLogger(__name__)


def health_check(request):
    """
    Проба живости для балансировщика и мониторинга хостинга.

    Платформа опрашивает этот адрес и перезапускает контейнер, если он
    молчит. Проверка дешёвая, но честная: простое «200 OK» скрыло бы
    отказавшую базу. Пингуем базу и кэш по отдельности, чтобы в ответе
    было видно, что именно упало.

    Статус ответа определяет ТОЛЬКО база: без неё сайт не работает, и
    перезапуск может помочь переподключиться. Кэш сообщаем отдельно, но
    из-за него в 503 не уходим — иначе внешний сбой Redis гонял бы
    контейнер по кругу перезапусков, ничего не исправляя.
    """
    database = "ok"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        database = "fail"

    cache_state = "ok"
    try:
        cache.set("healthz", "1", 5)
        if cache.get("healthz") != "1":
            cache_state = "fail"
    except Exception:
        cache_state = "fail"

    db_ok = database == "ok"
    return JsonResponse(
        {
            "status": "ok" if db_ok and cache_state == "ok" else "degraded",
            "database": database,
            "cache": cache_state,
        },
        status=200 if db_ok else 503,
    )


def serve_public_media(request, path, document_root=None):
    """Не позволяет обойти контроллер плеера прямой ссылкой на приватное медиа."""
    normalized_path = path.replace("\\", "/").lstrip("/")
    if normalized_path.startswith("private_media/"):
        raise Http404("Файл доступен только через защищённый маршрут.")
    return serve(request, path, document_root=document_root)


def cache_version(request):
    """
    Лёгкий эндпоинт для фронтенд-pooling'а.

    Возвращает текущую версию кэша. Клиент опрашивает раз в 60 секунд:
    если значение изменилось — пора обновить страницу.
    Один запрос = один cache.get(). Никакой нагрузки на базу.
    """
    response = JsonResponse({"v": get_cache_version()})
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


def sse_events(request):
    """
    Server-Sent Events: стримит события инвалидации кэша в реальном времени.

    Использует Redis Pub/Sub для кросс-процессной коммуникации.
    Если Redis недоступен — переходит в режим keepalive-пинга
    (клиент сам переключится на polling).

    ВАЖНО: SSE в WSGI (Gunicorn) блокирует воркер на всё время соединения.
    Для продакшена с сотнями одновременных пользователей используйте
    этот эндпоинт через ASGI-сервер (Daphne/Uvicorn) или полагайтесь
    на polling через /api/v1/cache-version/.
    """
    last_version = get_cache_version()

    def event_stream():
        nonlocal last_version

        redis_pubsub = None
        redis_client = None

        # Пытаемся подключиться к Redis Pub/Sub
        if settings.REDIS_URL:
            try:
                from redis import Redis

                redis_client = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
                redis_pubsub = redis_client.pubsub()
                redis_pubsub.subscribe("moviehub:cache:invalidate")
                logger.info("SSE: подключились к Redis Pub/Sub")
            except Exception as exc:
                logger.warning("SSE: Redis недоступен (%s), переходим в режим polling", exc)
                redis_pubsub = None

        yield "retry: 15000\n"  # переподключение через 15 секунд
        yield "event: connected\ndata: {}\n\n"

        last_keepalive = time.monotonic()

        try:
            while True:
                # Если есть Redis — слушаем Pub/Sub
                if redis_pubsub is not None:
                    try:
                        message = redis_pubsub.get_message(timeout=5.0)
                        if message and message["type"] == "message":
                            new_version = get_cache_version()
                            if new_version != last_version:
                                last_version = new_version
                                yield f"event: invalidate\ndata: {message['data'].decode()}\n\n"
                                yield f'event: update\ndata: {{"v": {new_version}}}\n\n'
                    except Exception:
                        # Redis отвалился — переключаемся на polling
                        redis_pubsub = None
                        continue

                # Если Redis нет — polling с keepalive
                now = time.monotonic()
                if now - last_keepalive >= 15.0:
                    new_version = get_cache_version()
                    if new_version != last_version:
                        last_version = new_version
                        yield f'event: update\ndata: {{"v": {new_version}}}\n\n'
                    yield ': keepalive\n\n'
                    last_keepalive = now
                else:
                    time.sleep(2.0)

        except GeneratorExit:
            pass
        finally:
            if redis_pubsub:
                try:
                    redis_pubsub.unsubscribe()
                    redis_pubsub.close()
                except Exception:
                    pass
            if redis_client:
                try:
                    redis_client.close()
                except Exception:
                    pass

    response = StreamingHttpResponse(
        event_stream(),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache, no-store"
    response["X-Accel-Buffering"] = "no"
    response["Connection"] = "keep-alive"
    # Отключаем сжатие: GZipMiddleware буферизирует стрим,
    # что убивает SSE (клиент не получает данные, пока стрим не закончится).
    response["Content-Encoding"] = "identity"
    return response


class ElidedPaginationMixin:
    """
    Добавляет в контекст готовый диапазон страниц вида 1 … 4 5 6 … 12.

    Нужен всем спискам с пагинацией: каталогу, избранному, истории.
    Без него шаблон includes/pagination.html выводит только
    кнопки «Назад» и «Вперёд», без номеров.

    on_each_side=1, on_ends=1 — сколько номеров показывать
    вокруг текущей страницы и по краям.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        paginator = context.get("paginator")

        if paginator:
            context["elided_page_range"] = paginator.get_elided_page_range(
                context["page_obj"].number, on_each_side=1, on_ends=1
            )
            context["ellipsis"] = paginator.ELLIPSIS

        return context
