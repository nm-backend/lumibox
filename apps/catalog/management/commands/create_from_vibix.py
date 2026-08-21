"""
Создание записей каталога из видеосервиса Vibix по Kinopoisk ID.

Заполнять каталог руками — минута на фильм плюс жанры и страны отдельными
кликами. Команда принимает список Kinopoisk ID и заводит по каждому готовую
опубликованную запись: название, год, imdb_id, player_id, описание, рейтинги,
длительность, жанры и страны — всё из ответа API видеосервиса.

    python manage.py create_from_vibix 447301 258687 361
    python manage.py create_from_vibix --file kp_ids.txt
    python manage.py create_from_vibix 447301 --dry-run

Отличие от sync_vibix: та команда обогащает уже существующие записи (ищет
совпадение по названию и году), а эта создаёт новые по точному Kinopoisk ID.

Идемпотентно: ID, у которого уже есть запись, пропускается — список можно
дополнять и запускать снова. Без VIBIX_API_TOKEN команда не запускается.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.video_service_api import VideoServiceAPIError, get_vibix_api_token
from apps.catalog.video_service_sync import create_title_from_vibix

# Человекочитаемая подпись исхода для строки лога по каждому ID.
_OUTCOME_LABEL = {
    "created": "создан",
    "exists": "уже есть — пропуск",
    "not_found": "нет в каталоге Vibix",
    "no_name": "без названия — пропуск",
    "no_year": "без года — пропуск",
}


class Command(BaseCommand):
    help = "Создаёт записи каталога из Vibix по списку Kinopoisk ID."

    def add_arguments(self, parser):
        parser.add_argument(
            "kp_ids",
            nargs="*",
            help="Kinopoisk ID через пробел.",
        )
        parser.add_argument(
            "--file",
            help="Файл со списком Kinopoisk ID, по одному в строке.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Ничего не пишет в базу, только показывает план.",
        )

    def handle(self, *args, **options):
        api_key = get_vibix_api_token()
        if not api_key:
            raise CommandError(
                "VIBIX_API_TOKEN не задан — команда не может обратиться к сервису."
            )

        kp_ids = self._collect_ids(options)
        if not kp_ids:
            raise CommandError(
                "Не передан ни один Kinopoisk ID (аргументы команды или --file)."
            )

        dry_run = options["dry_run"]
        counters = {key: 0 for key in _OUTCOME_LABEL}
        counters["error"] = 0

        for kp_id in kp_ids:
            try:
                title, outcome = create_title_from_vibix(api_key, kp_id, dry_run=dry_run)
            except VideoServiceAPIError as error:
                counters["error"] += 1
                self.stderr.write(f"[{kp_id}] ошибка API: {error}")
                continue

            counters[outcome] = counters.get(outcome, 0) + 1
            label = str(title) if title is not None else kp_id
            self.stdout.write(f"[{kp_id}] {_OUTCOME_LABEL.get(outcome, outcome)}: {label}")

        self.stdout.write(
            self.style.SUCCESS(
                "Итог — создано: {created}, уже было: {exists}, не найдено: "
                "{not_found}, без названия: {no_name}, без года: {no_year}, "
                "ошибок: {error}.".format(**counters)
            )
        )
        if dry_run:
            self.stdout.write("Сухой прогон — в базу ничего не записано.")

    def _collect_ids(self, options):
        """Kinopoisk ID из аргументов и --file, без дублей и с сохранением порядка."""
        kp_ids = list(options["kp_ids"])

        if options.get("file"):
            path = Path(options["file"])
            if not path.exists():
                raise CommandError(f"Файл со списком не найден: {path}")
            kp_ids += [
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        seen = set()
        unique = []
        for kp_id in kp_ids:
            if kp_id not in seen:
                seen.add(kp_id)
                unique.append(kp_id)
        return unique
