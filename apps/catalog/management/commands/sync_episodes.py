"""
Импорт серий сериалов из внешнего видеосервиса.

Тянет GET /serials/kp/{id} (или /serials/imdb/{id}) для сериалов
с kp_id/imdb_id и создаёт недостающие серии. Повторный запуск ничего
не дублирует, но добавляет появившиеся позже сезоны: пары «сезон + серия»
уникальны в пределах записи.

Примеры:
    python manage.py sync_episodes             # импортировать серии
    python manage.py sync_episodes --dry-run   # только отчёт, без записи
    python manage.py sync_episodes --limit 10  # не больше 10 записей
"""

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.video_service_api import VideoServiceAPIError
from apps.catalog.video_service_sync import sync_series_episodes


class Command(BaseCommand):
    help = "Импортирует серии сериалов (сезоны/эпизоды) из API видеосервиса."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Ничего не менять в базе — только посчитать, что было бы создано.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Обработать не больше N записей каталога (для отладки).",
        )

    def handle(self, *args, **options):
        try:
            stats = sync_series_episodes(
                dry_run=options["dry_run"], limit=options["limit"]
            )
        except VideoServiceAPIError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            f"Обработано записей: {stats['processed']}; создано серий: "
            f"{stats['created']}; не найдено в сервисе: {stats['not_found']}; "
            f"ошибок: {stats['errors']}."
        )
        if options["dry_run"]:
            self.stdout.write("Это был сухой прогон — в базу ничего не записано.")
