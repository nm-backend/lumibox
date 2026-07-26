"""
Фоновые задачи каталога.

Выполняются воркером Celery вне цикла запроса. Если Redis не настроен,
CELERY_TASK_ALWAYS_EAGER заставит их выполниться прямо на месте —
разработка от этого не встаёт.
"""

from decimal import Decimal

from celery import shared_task
from django.db.models import Avg, Count, Q

from apps.catalog.models import Title


@shared_task
def publish_scheduled_titles():
    """Публикует черновики с наступившей датой published_at."""
    from django.utils import timezone

    now = timezone.now()
    scheduled = Title.objects.filter(
        status=Title.Status.DRAFT,
        published_at__lte=now,
        published_at__isnull=False,
    )

    count = 0
    for title in scheduled:
        title.status = Title.Status.PUBLISHED
        title.save()
        count += 1

    return f"Опубликовано запланированных: {count}"


@shared_task
def refresh_title_ratings():
    """
    Пересчитывает рейтинги всех записей разом.

    Страховка, а не основной путь: при обычной работе рейтинг обновляет
    update_title_rating сразу после изменения отзыва. Эта задача чинит
    расхождения после массовых действий в админке и прямых правок в базе.

    bulk_update вместо save() в цикле: тысяча записей — это один запрос,
    а не тысяча.
    """
    # Импорт внутри задачи: на уровне модуля приложения ещё не загружены.
    from apps.reviews.models import Review

    published = Q(reviews__status=Review.Status.PUBLISHED)

    titles = list(
        Title.objects.annotate(
            computed_average=Avg("reviews__rating", filter=published),
            computed_count=Count("reviews", filter=published),
        )
    )

    changed = []
    for title in titles:
        average = title.computed_average
        new_average = Decimal(average).quantize(Decimal("0.1")) if average is not None else None

        # Пишем только то, что реально изменилось: незачем гонять
        # в базу тысячи одинаковых значений.
        if title.rating_average != new_average or title.rating_count != title.computed_count:
            title.rating_average = new_average
            title.rating_count = title.computed_count
            changed.append(title)

    if changed:
        Title.objects.bulk_update(changed, ["rating_average", "rating_count"], batch_size=500)

    return f"Обновлено записей: {len(changed)} из {len(titles)}"
