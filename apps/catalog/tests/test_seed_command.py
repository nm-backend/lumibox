"""
Тесты команды seed_catalog.

Команда важнее, чем кажется: именно её запускает человек, впервые
поднявший проект. Сломается она — сломается всё первое впечатление,
а заметить это без тестов можно только вручную, на живой базе.
"""

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.catalog.models import Country, Genre, Title
from apps.catalog.seed_data import COUNTRIES, GENRES, TITLES


class SeedCatalogTests(TestCase):
    def seed(self, **options):
        """Запускает команду, гася её вывод: в отчёте тестов он только мешает."""
        output = StringIO()
        call_command("seed_catalog", stdout=output, **options)
        return output.getvalue()

    def test_creates_everything_from_seed_data(self):
        self.seed()

        self.assertEqual(Genre.objects.count(), len(GENRES))
        self.assertEqual(Country.objects.count(), len(COUNTRIES))
        self.assertEqual(Title.objects.count(), len(TITLES))

    def test_links_genres_and_countries(self):
        """Связи важнее счётчиков: запись без жанров не найдётся фильтром."""
        self.seed()

        title = Title.objects.get(slug="nachalo-2010")
        self.assertGreater(title.genres.count(), 0)
        self.assertGreater(title.countries.count(), 0)

    def test_drafts_stay_drafts(self):
        """
        Два черновика в данных лежат намеренно: на них видно, что каталог
        показывает посетителю только опубликованное.
        """
        self.seed()

        drafts = Title.objects.filter(status=Title.Status.DRAFT)
        self.assertEqual(drafts.count(), 2)
        self.assertFalse(drafts.filter(published_at__isnull=False).exists())

    def test_published_titles_get_publication_date(self):
        self.seed()

        published = Title.objects.published()
        self.assertGreater(published.count(), 0)
        self.assertFalse(published.filter(published_at__isnull=True).exists())

    def test_running_twice_does_not_duplicate(self):
        """
        Команду запускают повторно — например, после добавления данных.
        update_or_create по slug должен обновлять, а не плодить дубли.
        """
        self.seed()
        self.seed()

        self.assertEqual(Title.objects.count(), len(TITLES))
        self.assertEqual(Genre.objects.count(), len(GENRES))

    def test_clear_option_wipes_before_filling(self):
        self.seed()
        Title.objects.create(name="Лишний", slug="lishniy", release_year=2020)

        self.seed(clear=True)

        self.assertFalse(Title.objects.filter(slug="lishniy").exists())
        self.assertEqual(Title.objects.count(), len(TITLES))

    def test_unknown_genre_stops_command_before_writing(self):
        """
        Опечатка в названии жанра должна остановить команду до записи,
        а не всплыть на середине невнятным KeyError с половиной данных в базе.
        """
        broken = [{**TITLES[0], "genres": ["Такого жанра нет"]}]

        with mock.patch("apps.catalog.management.commands.seed_catalog.TITLES", broken):
            with self.assertRaises(CommandError) as error:
                self.seed()

        self.assertIn("неизвестные жанры", str(error.exception))
        self.assertEqual(Title.objects.count(), 0, "база не должна пострадать")

    def test_unknown_country_stops_command(self):
        broken = [{**TITLES[0], "countries": ["Такой страны нет"]}]

        with mock.patch("apps.catalog.management.commands.seed_catalog.TITLES", broken):
            with self.assertRaises(CommandError) as error:
                self.seed()

        self.assertIn("неизвестные страны", str(error.exception))

    def test_seed_data_has_no_duplicate_slugs(self):
        """Дубль адреса уронил бы команду на ограничении уникальности."""
        slugs = [row["slug"] for row in TITLES]
        self.assertEqual(len(slugs), len(set(slugs)))
