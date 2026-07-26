"""
Prometheus метрики для MovieHub.

Эндпоинт /metrics/ отдаёт метрики в формате Prometheus.
Используется для мониторинга в Grafana.

Подключение в urls.py:
    path("metrics/", metrics_view, name="prometheus-metrics"),
"""

from django.db import connection
from django.http import HttpResponse


def metrics_view(request):
    """Отдаёт Prometheus-метрики."""
    from apps.catalog.models import Title
    from apps.reviews.models import Review
    from apps.users.models import User

    lines = []

    # Количество записей
    lines.append("# HELP moviehub_titles_total Total number of titles")
    lines.append("# TYPE moviehub_titles_total gauge")
    lines.append(f"moviehub_titles_total {Title.objects.count()}")

    lines.append("# HELP moviehub_titles_published Published titles")
    lines.append("# TYPE moviehub_titles_published gauge")
    lines.append(f"moviehub_titles_published {Title.objects.filter(status=Title.Status.PUBLISHED).count()}")

    movies_count = Title.objects.filter(
        type=Title.Type.MOVIE, status=Title.Status.PUBLISHED,
    ).count()
    lines.append("# HELP moviehub_titles_movies Movies count")
    lines.append("# TYPE moviehub_titles_movies gauge")
    lines.append(f"moviehub_titles_movies {movies_count}")

    series_count = Title.objects.filter(
        type=Title.Type.SERIES, status=Title.Status.PUBLISHED,
    ).count()
    lines.append("# HELP moviehub_titles_series Series count")
    lines.append("# TYPE moviehub_titles_series gauge")
    lines.append(f"moviehub_titles_series {series_count}")

    lines.append("# HELP moviehub_users_total Total registered users")
    lines.append("# TYPE moviehub_users_total gauge")
    lines.append(f"moviehub_users_total {User.objects.count()}")

    lines.append("# HELP moviehub_reviews_total Total reviews")
    lines.append("# TYPE moviehub_reviews_total gauge")
    lines.append(f"moviehub_reviews_total {Review.objects.count()}")

    # Популярность
    from django.db.models import Sum

    total_views = Title.objects.aggregate(total=Sum("view_count"))["total"] or 0
    lines.append("# HELP moviehub_views_total Total page views")
    lines.append("# TYPE moviehub_views_total counter")
    lines.append(f"moviehub_views_total {total_views}")

    # Database latency
    import time

    start = time.monotonic()
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    db_latency = round((time.monotonic() - start) * 1000, 2)
    lines.append("# HELP moviehub_db_latency_ms Database latency in milliseconds")
    lines.append("# TYPE moviehub_db_latency_ms gauge")
    lines.append(f"moviehub_db_latency_ms {db_latency}")

    content = "\n".join(lines) + "\n"
    return HttpResponse(content, content_type="text/plain; version=0.0.4; charset=utf-8")
