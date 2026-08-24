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

Наполнение каталога с нуля (массовый импорт всего списка издателя):

    python manage.py sync_vibix --create-missing --dry-run
        # план: сколько записей будет создано, без записи в базу
    python manage.py sync_vibix --create-missing
        # создать отсутствующие записи (черновики по умолчанию)
    python manage.py sync_vibix --create-missing --type serial
        # только сериалы; фильмы отдельно: --type movie
    python manage.py sync_vibix --unlock
        # снять зависшую блокировку массового импорта

Повторный запуск идемпотентен: заполняются только пустые поля, серии
не дублируются, существующие данные не удаляются. Массовый импорт можно
безопасно перезапускать после обрыва — существующие записи (дедуп по
kp_id) пропускаются, продолжение идёт с места остановки. Без
VIBIX_API_TOKEN команда завершается с понятной ошибкой, ничего не трогая.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import Title
from apps.catalog.video_service_api import VideoServiceAPIError
from apps.catalog.video_service_sync import (
    bulk_create_from_catalog,
    release_bulk_import_lock,
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
        parser.add_argument(
            "--create-missing",
            action="store_true",
            help=(
                "Массовый импорт: создать записи для видео издателя, которых "
                "ещё нет в каталоге. Новые записи — черновики."
            ),
        )
        parser.add_argument(
            "--type",
            dest="content_type",
            choices=["movie", "serial"],
            help="Только с --create-missing: обойти фильмы или сериалы раздельно.",
        )
        parser.add_argument(
            "--status",
            choices=["draft", "published"],
            default="draft",
            help="Только с --create-missing: статус новых записей (по умолчанию draft).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Только с --create-missing: размер батча записи в базу (по умолчанию 500).",
        )
        parser.add_argument(
            "--unlock",
            action="store_true",
            help="Снять блокировку массового импорта (если прошлый процесс умер).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if options["unlock"]:
            if any(options[name] for name in ("title", "voiceovers", "episodes", "create_missing")):
                raise CommandError("--unlock используется отдельно.")
            if release_bulk_import_lock():
                self.stdout.write(self.style.SUCCESS("Блокировка массового импорта снята."))
            else:
                self.stdout.write("Активной блокировки массового импорта нет.")
            return

        modes = ("title", "voiceovers", "episodes", "create_missing")
        selected_modes = sum(bool(options[name]) for name in modes)
        if selected_modes > 1:
            raise CommandError(
                "--title, --voiceovers, --episodes и --create-missing "
                "нельзя использовать вместе."
            )
        if options["limit"] is not None and not options["episodes"]:
            raise CommandError("--limit применяется только вместе с --episodes.")

        create_only = ("content_type", "status", "batch_size")
        if not options["create_missing"] and any(
            options[name] != default
            for name, default in (("content_type", None), ("status", "draft"), ("batch_size", 500))
        ):
            raise CommandError(
                f"{', '.join(('--' + name.replace('_', '-')) for name in create_only)} "
                "применяются только вместе с --create-missing."
            )

        if options["title"]:
            self._sync_one_title(options["title"], dry_run=dry_run)
            return

        if options["voiceovers"]:
            self._sync_voiceovers(dry_run=dry_run)
            return

        if options["episodes"]:
            self._sync_episodes(dry_run=dry_run, limit=options["limit"])
            return

        if options["create_missing"]:
            self._create_missing(
                content_type=options["content_type"],
                status=options["status"],
                batch_size=options["batch_size"],
                dry_run=dry_run,
                page_size=options["page_size"],
                max_pages=options["max_pages"],
            )
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

    def _create_missing(
        self, *, content_type, status, batch_size, dry_run, page_size, max_pages
    ):
        if batch_size < 1:
            raise CommandError("--batch-size должен быть положительным числом.")

        type_label = {"movie": "фильмы", "serial": "сериалы", None: "весь каталог"}[
            content_type
        ]
        self.stdout.write(
            f"Массовый импорт ({type_label}, статус новых записей: {status})..."
        )

        last_page = [0]

        def progress(snapshot):
            if snapshot["fetched"] // max(page_size, 1) <= last_page[0]:
                return
            last_page[0] = snapshot["fetched"] // max(page_size, 1)
            self.stdout.write(
                f"  … получено {snapshot['fetched']}, создано "
                f"{snapshot['created']}, уже есть {snapshot['skipped_existing']}"
            )

        try:
            stats = bulk_create_from_catalog(
                content_type=content_type,
                status=(
                    Title.Status.PUBLISHED if status == "published" else Title.Status.DRAFT
                ),
                dry_run=dry_run,
                page_size=page_size,
                max_pages=max_pages,
                batch_size=batch_size,
                progress=progress,
            )
        except VideoServiceAPIError as exc:
            raise CommandError(str(exc)) from exc
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        prefix = "План (без записи в базу)" if dry_run else "Импорт завершён"
        verb = "будет создано" if dry_run else "создано"
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}: получено карточек {stats['fetched']}, {verb} "
            f"{stats['created']} (батчей {stats['batches']}); пропущено как "
            f"существующие {stats['skipped_existing']}; без kp_id "
            f"{stats['no_kp_id']}, без названия {stats['no_name']}, "
            f"без года {stats['no_year']}; ошибок {stats['errors']}."
        ))
        self.stdout.write(
            f"Справочники: жанров +{stats['genres_created']}, "
            f"стран +{stats['countries_created']}."
        )
        for label, samples in (
            ("Без названия", stats["samples_no_name"]),
            ("Без года", stats["samples_no_year"]),
            ("Ошибки", stats["errors_log"]),
        ):
            for sample in samples:
                self.stdout.write(f"  · {label}: {sample}")
        if dry_run:
            self.stdout.write(self.style.WARNING("Сухой прогон: в базу ничего не записано."))
        elif stats["created"]:
            self.stdout.write(
                "Следующий шаг для сериалов: python manage.py sync_vibix --episodes"
            )
