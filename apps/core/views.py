from django.core.cache import cache
from django.db import connection
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.static import serve


def custom_404(request, exception):
    """Кастомная страница 404."""
    return render(request, "404.html", status=404)


def custom_500(request):
    """Кастомная страница 500."""
    return render(request, "500.html", status=500)


def health_check(request):
    """Проба живости для балансировщика и мониторинга."""
    import time
    start = time.monotonic()

    database = "ok"
    db_latency_ms = 0
    try:
        with connection.cursor() as cursor:
            db_start = time.monotonic()
            cursor.execute("SELECT 1")
            db_latency_ms = round((time.monotonic() - db_start) * 1000)
    except Exception:
        database = "fail"

    cache_state = "ok"
    cache_latency_ms = 0
    try:
        cache_start = time.monotonic()
        cache.set("healthz", "1", 5)
        if cache.get("healthz") != "1":
            cache_state = "fail"
        cache_latency_ms = round((time.monotonic() - cache_start) * 1000)
    except Exception:
        cache_state = "fail"

    db_ok = database == "ok"
    total_ms = round((time.monotonic() - start) * 1000)

    return JsonResponse(
        {
            "status": "ok" if db_ok and cache_state == "ok" else "degraded",
            "database": database,
            "database_latency_ms": db_latency_ms,
            "cache": cache_state,
            "cache_latency_ms": cache_latency_ms,
            "total_latency_ms": total_ms,
        },
        status=200 if db_ok else 503,
    )


def serve_public_media(request, path, document_root=None):
    """Не позволяет обойти контроллер плеера прямой ссылкой на приватное медиа."""
    normalized_path = path.replace("\\", "/").lstrip("/")
    if normalized_path.startswith("private_media/"):
        raise Http404("Файл доступен только через защищённый маршрут.")
    return serve(request, path, document_root=document_root)


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
