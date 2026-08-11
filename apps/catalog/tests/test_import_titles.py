"""
Тесты массовой загрузки каталога.

Команда нужна ровно для одного: залить каталог из файла, не заводя триста
записей руками. Поэтому проверяется не «отработала без ошибки», а то, ради
чего её запускают: записи созданы, справочники подхвачены, повторный запуск
не плодит дубли и не стирает уже загруженные картинки.
"""

import json
import tempfile
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Country, Episode, Genre, Title


def write_json(payload):
    """Кладёт данные во временный файл и возвращает путь к нему."""
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(payload, handle, ensure_ascii=False)
    handle.close()
    return handle.name


class ImportTitlesTests(TestCase):
    def test_creates_title_with_references(self):
        path = write_json([{
            "name": "Импортированный фильм",
            "original_name": "Imported Movie",
            "type": "movie",
            "release_year": 2024,
            "genres": ["Драма", "Триллер"],
            "countries": ["США"],
            "duration_minutes": 120,
        }])

        call_command("import_titles", path)

        title = Title.objects.get(name="Импортированный фильм")
        self.assertEqual(title.slug, "imported-movie-2024")
        self.assertEqual(title.duration_minutes, 120)
        self.assertEqual(
            sorted(genre.name for genre in title.genres.all()),
            ["Драма", "Триллер"],
        )
        self.assertEqual([c.name for c in title.countries.all()], ["США"])

    def test_reuses_existing_reference_by_name(self):
        """
        Жанр ищется по названию, а не по адресу.

        Существующая «Драма» могла получить адрес drama-1 при ручной правке.
        Поиск по адресу её не находил, команда пыталась создать вторую —
        и весь импорт падал на уникальности имени.
        """
        Genre.objects.create(name="Драма", slug="drama-1")
        path = write_json([{"name": "Фильм", "genres": ["Драма"]}])

        call_command("import_titles", path)

        self.assertEqual(Genre.objects.filter(name="Драма").count(), 1)
        self.assertEqual(Title.objects.get(name="Фильм").genres.first().slug, "drama-1")

    def test_cyrillic_titles_get_distinct_addresses(self):
        """
        Название без латиницы не должно схлопывать записи в один адрес.

        Раньше для такого названия подставлялась заглушка «title», и два
        русскоязычных фильма одного года затирали друг друга.
        """
        path = write_json([
            {"name": "Первый фильм", "release_year": 2020},
            {"name": "Второй фильм", "release_year": 2020},
        ])

        call_command("import_titles", path)

        slugs = set(Title.objects.values_list("slug", flat=True))
        self.assertEqual(len(slugs), 2)
        self.assertEqual(Title.objects.count(), 2)

    def test_address_is_usable_in_urls(self):
        """
        Адрес обязан подходить под маршрут <slug:...>, то есть быть латиницей.

        Кириллический адрес сохраняется в базу, но ссылку на такую запись
        собрать нельзя: reverse() падает с NoReverseMatch, и любая страница
        со списком, где эта запись попадается, перестаёт открываться целиком.
        Проверяем не вид адреса, а именно то, ради чего он нужен, — что по
        нему собирается ссылка и страница отвечает.
        """
        path = write_json([{"name": "Тьма", "release_year": 2017}])
        call_command("import_titles", path)

        title = Title.objects.get()
        self.assertRegex(title.slug, r"^[-a-zA-Z0-9_]+$")

        response = self.client.get(title.get_absolute_url())
        self.assertEqual(response.status_code, 200)

    def test_reference_address_is_usable_in_urls(self):
        """Жанру нужен пригодный адрес по той же причине — маршрут жанра."""
        path = write_json([{"name": "Фильм", "genres": ["Мистика"]}])
        call_command("import_titles", path)

        genre = Genre.objects.get(name="Мистика")
        self.assertRegex(genre.slug, r"^[-a-zA-Z0-9_]+$")

        response = self.client.get(
            reverse("catalog:genre_titles", args=[genre.slug])
        )
        self.assertEqual(response.status_code, 200)

    def test_second_run_updates_and_does_not_duplicate(self):
        path = write_json([{
            "name": "Фильм",
            "original_name": "Movie",
            "release_year": 2024,
            "description": "Первая версия",
        }])
        call_command("import_titles", path)

        path2 = write_json([{
            "name": "Фильм",
            "original_name": "Movie",
            "release_year": 2024,
            "description": "Исправленное описание",
        }])
        call_command("import_titles", path2)

        self.assertEqual(Title.objects.count(), 1)
        self.assertEqual(Title.objects.get().description, "Исправленное описание")

    def test_existing_poster_survives_reimport(self):
        """
        Повторный импорт без поля poster не должен стирать загруженную обложку:
        файл мог быть добавлен через админку уже после первой заливки.
        """
        path = write_json([{"name": "Фильм", "original_name": "Movie", "release_year": 2024}])
        call_command("import_titles", path)
        title = Title.objects.get()
        title.poster = "posters/manual.jpg"
        title.save(update_fields=["poster"])

        call_command("import_titles", path)

        self.assertEqual(Title.objects.get().poster.name, "posters/manual.jpg")

    def test_creates_episodes_for_series(self):
        path = write_json([{
            "name": "Сериал",
            "original_name": "Series",
            "type": "series",
            "release_year": 2023,
            "episodes": [
                {"season": 1, "number": 1, "name": "Первая", "duration": 45},
                {"season": 1, "number": 2, "name": "Вторая", "duration": 44},
            ],
        }])

        call_command("import_titles", path)

        title = Title.objects.get()
        self.assertEqual(title.episodes.count(), 2)
        self.assertEqual(Episode.objects.get(episode_number=2).name, "Вторая")

    def test_dry_run_changes_nothing(self):
        path = write_json([{"name": "Фильм", "release_year": 2024}])

        call_command("import_titles", path, dry_run=True)

        self.assertEqual(Title.objects.count(), 0)

    def test_broken_file_is_refused_whole(self):
        """
        Файл проверяется целиком до первой записи в базу: залить половину
        каталога и упасть на середине хуже, чем не залить ничего.
        """
        path = write_json([
            {"name": "Хороший фильм"},
            {"name": ""},
        ])

        with self.assertRaises(CommandError):
            call_command("import_titles", path)

        self.assertEqual(Title.objects.count(), 0)

    def test_missing_file_reports_clearly(self):
        with self.assertRaises(CommandError):
            call_command("import_titles", str(Path(tempfile.gettempdir()) / "нет-такого.json"))

    def test_not_a_list_is_refused(self):
        path = write_json({"name": "Одна запись без списка"})

        with self.assertRaises(CommandError):
            call_command("import_titles", path)

        self.assertEqual(Country.objects.count(), 0)
