from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.models import Country, Genre, Title
from apps.catalog.seed_data import COUNTRIES, GENRES, TITLES


class Command(BaseCommand):
    """
    Наполняет каталог тестовыми данными.

    Команду можно запускать сколько угодно раз: она не создаёт дубликаты,
    а обновляет существующие записи по адресу (slug).
    """

    help = "Наполняет каталог тестовыми жанрами, странами, фильмами и сериалами."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Удалить записи каталога перед наполнением",
        )

    # Вся команда — одна транзакция: при ошибке на середине база
    # останется в исходном состоянии, а не с половиной данных.
    @transaction.atomic
    def handle(self, *args, **options):
        self._check_data()

        if options["clear"]:
            self._clear()

        genres = self._load_references(Genre, GENRES)
        countries = self._load_references(Country, COUNTRIES)
        self._load_titles(genres, countries)

        self.stdout.write(self.style.SUCCESS("Каталог наполнен."))

    def _check_data(self):
        """
        Проверяет данные до записи в базу.

        Опечатка в названии жанра иначе всплыла бы посреди работы
        невнятной ошибкой KeyError.
        """
        known_genres = {name for name, _ in GENRES}
        known_countries = {name for name, _ in COUNTRIES}

        for row in TITLES:
            unknown_genres = set(row["genres"]) - known_genres
            unknown_countries = set(row["countries"]) - known_countries
            if unknown_genres:
                raise CommandError(f"{row['name']}: неизвестные жанры {unknown_genres}")
            if unknown_countries:
                raise CommandError(f"{row['name']}: неизвестные страны {unknown_countries}")

    def _clear(self):
        deleted_titles, _ = Title.objects.all().delete()
        Genre.objects.all().delete()
        Country.objects.all().delete()
        self.stdout.write(f"Удалено записей каталога: {deleted_titles}")

    def _load_references(self, model, rows):
        """Создаёт жанры или страны и возвращает их в виде {название: объект}."""
        references = {}
        created_count = 0

        for name, slug in rows:
            reference, created = model.objects.get_or_create(
                name=name,
                defaults={"slug": slug},
            )
            references[name] = reference
            created_count += int(created)

        self.stdout.write(f"{model._meta.verbose_name_plural}: создано {created_count}, всего {len(rows)}")
        return references

    def _load_titles(self, genres, countries):
        created_count = 0

        for row in TITLES:
            # Жанры и страны — связи многие-ко-многим, их нельзя передать
            # в update_or_create, поэтому проставляем отдельно ниже.
            fields = {key: value for key, value in row.items() if key not in ("slug", "genres", "countries")}

            title, created = Title.objects.update_or_create(slug=row["slug"], defaults=fields)
            title.genres.set(genres[name] for name in row["genres"])
            title.countries.set(countries[name] for name in row["countries"])
            created_count += int(created)

        published = sum(1 for row in TITLES if row["status"] == "published")
        self.stdout.write(
            f"Фильмы и сериалы: создано {created_count}, всего {len(TITLES)} "
            f"(опубликовано {published}, черновиков {len(TITLES) - published})"
        )
