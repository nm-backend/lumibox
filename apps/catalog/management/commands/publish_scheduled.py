"""
Публикует запланированные фильмы и сериалы.

Если у черновика стоит published_at в будущем — он будет опубликован
когда наступит это время. Запускается по расписанию (cron/celery beat).

Запуск:
    python manage.py publish_scheduled
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.catalog.models import Title


class Command(BaseCommand):
    help = "Публикует черновики с наступившей датой published_at."

    def handle(self, *args, **options):
        now = timezone.now()
        scheduled = Title.objects.filter(
            status=Title.Status.DRAFT,
            published_at__lte=now,
            published_at__isnull=False,
        )

        count = 0
        for title in scheduled:
            title.status = Title.Status.PUBLISHED
            title.save()  # save() проставит published_at если нужно
            count += 1
            self.stdout.write(f"  Опубликовано: {title.name}")

        if count:
            self.stdout.write(self.style.SUCCESS(f"Опубликовано записей: {count}"))
        else:
            self.stdout.write("Нет запланированных публикаций.")
