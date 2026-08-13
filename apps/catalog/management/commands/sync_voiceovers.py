"""
Синхронизация озвучек каталога с внешним видеосервисом.

Тянет список озвучек из API видеосервиса (GET /videos/voiceovers)
и проставляет их ID озвучкам каталога по совпадению названия.
Заполняются только пустые поля; вручную введённые ID не затираются.

Заполненные ID используются вкладкой внешнего плеера как data-voiceover:
озвучка по умолчанию, которую зритель может переключить в самом плеере.

Примеры:
    python manage.py sync_voiceovers              # заполнить сопоставления
    python manage.py sync_voiceovers --dry-run    # только отчёт, без записи
"""

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.video_service_api import VideoServiceAPIError
from apps.catalog.video_service_voiceover_sync import sync_voiceover_ids


class Command(BaseCommand):
    help = "Проставляет ID озвучек сервиса (vibix_voiceover_id) по названиям."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Ничего не менять в базе — только посчитать, что было бы заполнено.",
        )

    def handle(self, *args, **options):
        try:
            stats = sync_voiceover_ids(dry_run=options["dry_run"])
        except VideoServiceAPIError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            f"Озвучек от сервиса: {stats['fetched']}; "
            f"заполнено сопоставлений: {stats['filled']}."
        )
        if options["dry_run"]:
            self.stdout.write("Это был сухой прогон — в базу ничего не записано.")
