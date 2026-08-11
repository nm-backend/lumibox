"""
Массовая загрузка каталога из JSON.

Заполнить каталог руками через админку — это по минуте на запись плюс жанры
и страны отдельными кликами. Для тридцати фильмов терпимо, для трёхсот уже
нет. Команда принимает один файл и создаёт всё разом: сами записи, жанры,
страны и студии по названиям, серии у сериалов.

Формат — список объектов. Обязательное поле одно, название:

    [
      {
        "name": "Начало",
        "original_name": "Inception",
        "type": "movie",
        "release_year": 2010,
        "description": "Вор проникает в чужие сны.",
        "genres": ["Фантастика", "Триллер"],
        "countries": ["США"],
        "duration_minutes": 148,
        "age_rating": "16+",
        "quality": "WEB-DL",
        "status": "published",
        "poster": "posters/nachalo.jpg",
        "episodes": [{"season": 1, "number": 1, "name": "Пилот", "duration": 45}]
      }
    ]

Поля poster и backdrop — пути внутри MEDIA_ROOT: файлы кладутся туда заранее,
команда только связывает их с записью. Загружать картинки по адресам из
интернета она не будет — это чужой трафик и чужие права.

Повторный запуск того же файла ничего не ломает: записи ищутся по slug,
существующие обновляются. Поэтому файл можно править и заливать снова.

Примеры:
    python manage.py import_titles catalog.json
    python manage.py import_titles catalog.json --dry-run
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from apps.catalog.models import Country, Episode, Genre, Studio, Title

# Кириллица → латиница для адресов.
#
# Адреса в маршрутах описаны как <slug:...>, а этот преобразователь принимает
# только [-a-zA-Z0-9_]. Кириллический адрес формально сохраняется в базу, но
# ссылку на такую запись собрать уже нельзя: reverse() падает с NoReverseMatch,
# и страница со списком, где эта запись попадается, перестаёт открываться
# целиком. Поэтому русские названия транслитерируем, а не оставляем как есть.
TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def transliterate(text: str) -> str:
    """Русский текст латиницей: «Тьма» → «tma»."""
    return "".join(TRANSLIT.get(char, TRANSLIT.get(char.lower(), char)) for char in text.lower())


class Command(BaseCommand):
    help = "Загружает фильмы и сериалы из JSON-файла. Идемпотентна."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Путь к JSON-файлу со списком записей")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Разобрать файл и показать, что будет сделано, но ничего не менять",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"Файл не найден: {path}")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise CommandError(f"Файл не разбирается как JSON: {error}") from error

        if not isinstance(payload, list):
            raise CommandError("Ожидается список записей на верхнем уровне файла")

        # Проверяем весь файл до первой записи в базу: лучше отказать целиком,
        # чем залить половину каталога и упасть на середине.
        for number, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                raise CommandError(f"Запись {number}: ожидается объект, получено {type(item).__name__}")
            if not item.get("name"):
                raise CommandError(f"Запись {number}: обязательное поле name пустое")

        if options["dry_run"]:
            self._report_plan(payload)
            return

        created, updated, episodes = 0, 0, 0
        with transaction.atomic():
            for item in payload:
                title, was_created = self._save_title(item)
                created += was_created
                updated += not was_created
                episodes += self._save_episodes(title, item.get("episodes") or [])

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово. Создано: {created}, обновлено: {updated}, серий: {episodes}."
            )
        )
        self.stdout.write(
            "Обложки для записей без картинки: python manage.py generate_placeholder_art"
        )

    def _report_plan(self, payload):
        existing = set(Title.objects.values_list("slug", flat=True))
        create = sum(1 for item in payload if self._slug_for(item) not in existing)
        self.stdout.write(f"Записей в файле: {len(payload)}")
        self.stdout.write(f"Будет создано: {create}, обновлено: {len(payload) - create}")
        self.stdout.write(f"Серий: {sum(len(item.get('episodes') or []) for item in payload)}")
        self.stdout.write("Ничего не записано: это пробный запуск.")

    def _slug_for(self, item):
        """
        Адрес записи. Год в хвосте — чтобы ремейк не занял адрес оригинала:
        «Дюна» 1984 и 2021 иначе схлопнулись бы в одну запись.

        Название без латиницы транслитерируем: раньше все русскоязычные
        фильмы одного года получали адрес-заглушку «title» и затирали друг
        друга при импорте. Кириллица в адресе тоже не подходит — маршруты
        описаны как <slug:...>, и ссылку на такую запись собрать нельзя.
        """
        if item.get("slug"):
            return item["slug"]
        source = item.get("original_name") or item["name"]
        base = slugify(source, allow_unicode=False) or slugify(transliterate(source))
        if not base:
            base = "title"
        year = item.get("release_year")
        return f"{base}-{year}" if year else base

    def _save_title(self, item):
        fields = {
            "name": item["name"],
            "original_name": item.get("original_name", ""),
            "type": item.get("type", Title.Type.MOVIE),
            "release_year": item.get("release_year") or 0,
            "description": item.get("description", ""),
            "short_description": item.get("short_description", ""),
            "duration_minutes": item.get("duration_minutes"),
            "age_rating": item.get("age_rating", ""),
            "quality": item.get("quality", ""),
            "status": item.get("status", Title.Status.PUBLISHED),
        }
        # Картинки не перетираем пустотой: файл мог быть загружен раньше
        # вручную, и повторный импорт не должен его стирать.
        for key in ("poster", "backdrop"):
            if item.get(key):
                fields[key] = item[key]

        title, created = Title.objects.update_or_create(
            slug=self._slug_for(item), defaults=fields
        )

        if item.get("genres"):
            title.genres.set(self._references(Genre, item["genres"]))
        if item.get("countries"):
            title.countries.set(self._references(Country, item["countries"]))
        if item.get("studios"):
            title.studios.set(self._references(Studio, item["studios"]))

        return title, created

    def _references(self, model, names):
        """
        Справочник по названию: существующее берём, недостающее заводим.

        Иначе импорт требовал бы заранее завести все жанры и страны руками —
        и падал бы на первом же названии, которого нет в базе.

        Ищем по названию, а не по адресу, хотя уникальны оба. Название —
        это то, что написано в файле; адрес у существующей записи мог быть
        задан иначе (кириллица, ручная правка, транслитерация другой
        версией slugify). Поиск по адресу на «Драме» с адресом drama-1
        не находил её и пытался создать вторую «Драму» — база отвечала
        нарушением уникальности имени, и весь импорт падал.
        """
        objects = []
        for name in names:
            name = str(name).strip()
            if not name:
                continue
            obj = model.objects.filter(name__iexact=name).first()
            if obj is None:
                obj = model.objects.create(
                    name=name,
                    slug=self._unique_slug(model, name),
                )
            objects.append(obj)
        return objects

    def _unique_slug(self, model, name):
        """
        Свободный адрес для нового элемента справочника.

        slugify кириллицы даёт пустую строку, а два разных названия могут
        дать один адрес — в обоих случаях запись не создалась бы. Добавляем
        числовой хвост, пока адрес не окажется свободным.
        """
        base = slugify(name, allow_unicode=False) or slugify(transliterate(name)) or "item"
        slug, suffix = base, 2
        while model.objects.filter(slug=slug).exists():
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

    def _save_episodes(self, title, episodes):
        saved = 0
        for episode in episodes:
            season = int(episode.get("season", 1))
            number = int(episode.get("number", 1))
            Episode.objects.update_or_create(
                title=title,
                season_number=season,
                episode_number=number,
                defaults={
                    "name": episode.get("name", ""),
                    "duration_minutes": episode.get("duration"),
                },
            )
            saved += 1
        return saved
