"""
Единая точка входа для синхронизации с видеосервисом Vibix.

Заменяет три старые команды (sync_video_service, sync_episodes,
sync_voiceovers — остаются для обратной совместимости) одной:

    python manage.py sync_vibix                # инкрементальный синк каталога
    python manage.py sync_vibix --full         # полный обход каталога сервиса
    python manage.py sync_vibix --title <slug> # одна запись каталога
    python manage.py sync_vibix --voiceovers   # сопоставление озвучек
    python manage.py sync_vibix --episodes     # новые сезоны и серии
    python manage.py sync_vibix --dry-run      # ничего не пишет в базу

Повторный запуск идемпотентен: заполняются только пустые поля, серии
не дублируются, существующие данные не удаляются. Без VIBIX_API_TOKEN
команда завершается с понятной ошибкой, ничего не трогая.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import Title
from apps.catalog.video_service_api import VideoServiceAPIError
from apps.catalog.video_service_sync import (
    sync_series_episodes,
    sync_title,
    sync_video_service_ids,
)
from apps.catalog.video_service_voiceover_sync import sync_voiceover_ids


class Command(BaseCommand):
    help = "Синхронизация каталога с видеосервисом Vibix (kp/imdb/player_id, серии, озвучки)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--full",
            action="store_true",
            help="Полный обход каталога сервиса вместо инкрементального (по updated_from).",
        )
        parser.add_argument(
            "--title",
            metavar="SLUG",
            help="Синхронизировать только одну запись каталога по её адресу (slug).",
        )
        parser.add_argument(
            "--voiceovers",
            action="store_true",
            help="Сопоставить озвучки каталога с озвучками сервиса (vibix_voiceover_id).",
        )
        parser.add_argument(
            "--episodes",
            action="store_true",
            help="Добавить недостающие сезоны и серии для всех сериалов с KP/IMDb ID.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="С --episodes обработать не больше N сериалов (для проверки).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Ничего не писать в базу: показать, что было бы сделано.",
        )
        parser.add_argument(
            "--page-size",
            type=int,
            default=100,
            help="Записей сервиса на страницу списка (по умолчанию 100).",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            help="Ограничение числа страниц списка (для отладки).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        selected_modes = sum(bool(options[name]) for name in ("title", "voiceovers", "episodes"))
        if selected_modes > 1:
            raise CommandError("--title, --voiceovers и --episodes нельзя использовать вместе.")
        if options["limit"] is not None and not options["episodes"]:
            raise CommandError("--limit применяется только вместе с --episodes.")

        if options["title"]:
            self._sync_one_title(options["title"], dry_run=dry_run)
            return

        if options["voiceovers"]:
            self._sync_voiceovers(dry_run=dry_run)
            return

        if options["episodes"]:
            self._sync_episodes(dry_run=dry_run, limit=options["limit"])
            return

        self._sync_catalog(
            full=options["full"],
            dry_run=dry_run,
            page_size=options["page_size"],
            max_pages=options["max_pages"],
        )

    def _sync_catalog(self, *, full, dry_run, page_size, max_pages):
        try:
            stats = sync_video_service_ids(
                full=full, dry_run=dry_run, page_size=page_size, max_pages=max_pages
            )
        except VideoServiceAPIError as exc:
            raise CommandError(str(exc))

        mode = "полный" if full else "инкрементальный"
        self.stdout.write(self.style.SUCCESS(
            f"Синк каталога ({mode}): получено {stats['fetched']}, "
            f"совпадений {stats['matched']}, kp_id {stats['kp_filled']}, "
            f"imdb_id {stats['imdb_filled']}, player_id {stats['player_filled']}, "
            f"обогащено {stats['enriched']}"
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("Сухой прогон: в базу ничего не записано."))

    def _sync_one_title(self, slug, *, dry_run):
        try:
            title = Title.objects.get(slug=slug)
        except Title.DoesNotExist:
            raise CommandError(f"Запись с адресом «{slug}» не найдена.")

        if not title.kp_id.strip() and not title.imdb_id.strip():
            raise CommandError(
                f"У записи «{title.name}» нет kp_id/imdb_id — укажите их в админке."
            )

        try:
            stats = sync_title(title, dry_run=dry_run)
        except VideoServiceAPIError as exc:
            raise CommandError(str(exc))

        if stats["not_found"]:
            self.stdout.write(self.style.WARNING(
                f"«{title.name}»: видео с таким kp/imdb ID в каталоге сервиса не найдено."
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f"«{title.name}»: player_id {stats['player_filled'] and 'заполнен' or 'уже был'}, "
            f"обогащено {stats['enriched'] and 'да' or 'нет'}, "
            f"серий создано {stats['episodes_created']}"
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("Сухой прогон: в базу ничего не записано."))

    def _sync_voiceovers(self, *, dry_run):
        try:
            stats = sync_voiceover_ids(dry_run=dry_run)
        except VideoServiceAPIError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            f"Озвучки: получено {stats['fetched']}, сопоставлено {stats['filled']}"
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("Сухой прогон: в базу ничего не записано."))

    def _sync_episodes(self, *, dry_run, limit):
        try:
            stats = sync_series_episodes(dry_run=dry_run, limit=limit)
        except VideoServiceAPIError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            f"Сериалы: обработано {stats['processed']}, создано серий "
            f"{stats['created']}, не найдено {stats['not_found']}, "
            f"ошибок {stats['errors']}"
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("Сухой прогон: в базу ничего не записано."))
