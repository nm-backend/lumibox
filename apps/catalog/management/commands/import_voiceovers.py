"""Импорт справочника озвучек из видеосервиса.

Озвучки в каталоге заводит редактор, и на свежем сайте справочник пуст —
а без записей не заполнится и data-voiceover внешнего плеера. Команда
тянет GET /videos/voiceovers и создаёт недостающие озвучки сразу
с vibix_voiceover_id. Существующие записи не дублируются, вручную
введённый ID не затирается.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.video_service_api import VideoServiceAPIError
from apps.catalog.video_service_voiceover_sync import import_voiceovers_from_service


class Command(BaseCommand):
    help = "Создаёт озвучки каталога из справочника видеосервиса. Идемпотентна."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать, что будет создано, но ничего не менять",
        )

    def handle(self, *args, **options):
        try:
            stats = import_voiceovers_from_service(dry_run=options["dry_run"])
        except VideoServiceAPIError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            f"Озвучек от сервиса: {stats['fetched']}; создано: {stats['created']}; "
            f"заполнено у существующих: {stats['filled']}."
        )
        if options["dry_run"]:
            self.stdout.write("Это был сухой прогон — в базу ничего не записано.")
