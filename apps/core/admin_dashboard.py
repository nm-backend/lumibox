"""
Аналитический дашборд для админки.

Показывает ключевые метрики: пользователи, просмотры, рейтинги, популярные фильмы.
Доступен только staff через /admin/dashboard/.
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from apps.catalog.models import Title
from apps.reviews.models import Review
from apps.streaming.models import WatchProgress

User = get_user_model()


@staff_member_required
def admin_dashboard(request):
    """Страница аналитики в админке."""
    now = timezone.now()
    last_30_days = now - timezone.timedelta(days=30)

    # Общая статистика
    total_titles = Title.objects.published().count()
    total_movies = Title.objects.published().movies().count()
    total_series = Title.objects.published().series().count()

    # Просмотры
    total_views = Title.objects.published().aggregate(total=Sum("view_count"))["total"] or 0
    top_viewed = Title.objects.published().order_by("-view_count")[:10]

    # Рейтинги
    avg_rating = Title.objects.published().filter(rating_count__gt=0).aggregate(
        avg=Avg("rating_average")
    )["avg"]
    top_rated = Title.objects.published().filter(rating_count__gt=0).order_by("-rating_average")[:10]

    # Отзывы
    total_reviews = Review.objects.count()
    recent_reviews = Review.objects.select_related("user", "title").order_by("-created_at")[:10]
    hidden_reviews = Review.objects.filter(status="hidden").count()
    published_reviews = Review.objects.filter(status="published").count()

    # Активность просмотров
    active_watchers = WatchProgress.objects.filter(
        last_watched_at__gte=last_30_days
    ).values("user").distinct().count()

    # Недосмотренное
    in_progress = WatchProgress.objects.filter(
        is_completed=False,
        position_seconds__gte=30,
    ).count()

    # Пользователи
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    staff_users = User.objects.filter(is_staff=True).count()
    recent_users = User.objects.order_by("-date_joined")[:10]

    # Самые активные зрители (по количеству просмотров)
    top_viewers = (
        WatchProgress.objects.filter(last_watched_at__gte=last_30_days)
        .values("user__email", "user__username")
        .annotate(watch_count=Count("id"))
        .order_by("-watch_count")[:10]
    )

    # Конверсия: сколько пользователей оставили хотя бы один отзыв
    users_with_reviews = Review.objects.values("user").distinct().count()
    review_conversion = round(users_with_reviews / total_users * 100, 1) if total_users > 0 else 0

    # Среднее количество просмотров на фильм
    avg_views_per_title = round(total_views / total_titles, 1) if total_titles > 0 else 0

    context = {
        "total_titles": total_titles,
        "total_movies": total_movies,
        "total_series": total_series,
        "total_views": total_views,
        "top_viewed": top_viewed,
        "avg_rating": avg_rating,
        "top_rated": top_rated,
        "total_reviews": total_reviews,
        "recent_reviews": recent_reviews,
        "hidden_reviews": hidden_reviews,
        "published_reviews": published_reviews,
        "active_watchers": active_watchers,
        "in_progress": in_progress,
        "total_users": total_users,
        "active_users": active_users,
        "staff_users": staff_users,
        "recent_users": recent_users,
        "top_viewers": top_viewers,
        "review_conversion": review_conversion,
        "avg_views_per_title": avg_views_per_title,
    }
    return render(request, "admin/dashboard.html", context)


@staff_member_required
def admin_dashboard_api(request):
    """API endpoint для дашборда — возвращает JSON с метриками."""
    now = timezone.now()
    last_30_days = now - timezone.timedelta(days=30)

    total_titles = Title.objects.published().count()
    total_views = Title.objects.published().aggregate(total=Sum("view_count"))["total"] or 0
    total_reviews = Review.objects.count()
    total_users = User.objects.count()
    active_watchers = WatchProgress.objects.filter(
        last_watched_at__gte=last_30_days
    ).values("user").distinct().count()

    return JsonResponse({
        "total_titles": total_titles,
        "total_views": total_views,
        "total_reviews": total_reviews,
        "total_users": total_users,
        "active_watchers": active_watchers,
        "timestamp": now.isoformat(),
    })
