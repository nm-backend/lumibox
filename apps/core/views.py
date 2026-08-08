from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse


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
    """Не позволяет обойти контроллер плеера прямой ссылкой на приватное медиа.

    Раздаёт файл через media_serving.serve_public_media — Range-запросы
    (206), защита от обхода каталога и кэш-заголовки.
    """
    from apps.core.media_serving import serve_public_media as _serve

    return _serve(request, path, document_root=document_root)

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
