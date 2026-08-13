"""
Синхронизация ID каталога с внешним видеосервисом.

Тянет список видео из API видеосервиса (GET /videos/links) и проставляет
записям каталога Kinopoisk/IMDb-идентификаторы и внутренний ID плеера —
по совпадению названия и года. Заполняются только пустые поля; вручную
введённые ID не затираются.

Запуск в первый раз тянет весь каталог, дальше — только изменённые видео
(API параметр updated_from, отметка хранится в базе).

Примеры:
    python manage.py sync_video_service                # инкрементальный запуск
    python manage.py sync_video_service --dry-run      # только отчёт, без записи
    python manage.py sync_video_service --full         # тянуть всё заново
"""

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.video_service_api import VideoServiceAPIError
from apps.catalog.video_service_sync import sync_video_service_ids


class Command(BaseCommand):
    help = "Проставляет kp_id/imdb_id/player_id записям каталога из API видеосервиса."

    def add_arguments(self, parser):
        parser.add_argument(
            "--full",
            action="store_true",
            help="Тянуть весь список видео, игнорируя сохранённую отметку updated_from.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Ничего не менять в базе — только посчитать, что было бы заполнено.",
        )
        parser.add_argument(
            "--page-size",
            type=int,
            default=100,
            help="Записей на страницу запроса (лимит API, по умолчанию 100).",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            default=None,
            help="Не тянуть больше этого числа страниц (для отладки).",
        )

    def handle(self, *args, **options):
        try:
            stats = sync_video_service_ids(
                full=options["full"],
                dry_run=options["dry_run"],
                page_size=options["page_size"],
                max_pages=options["max_pages"],
            )
        except VideoServiceAPIError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            f"Обработано видео: {stats['fetched']}; совпадений с каталогом: "
            f"{stats['matched']}; заполнено kp_id: {stats['kp_filled']}; "
            f"заполнено imdb_id: {stats['imdb_filled']}; "
            f"заполнено player_id: {stats['player_filled']}."
        )
        if options["dry_run"]:
            self.stdout.write("Это был сухой прогон — в базу ничего не записано.")
