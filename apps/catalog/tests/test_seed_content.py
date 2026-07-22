"""
Тесты команды seed_content — того, что превращает список названий в живой
каталог: съёмочной группы, подборок и оценок. Проверяем и сам факт наполнения,
и идемпотентность: команду запускают повторно, дубликатов быть не должно.
"""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.catalog.models import Collection, Participation, Person, Title
from apps.catalog.seed_data import COLLECTIONS, CREDITS, PERSONS, REVIEWS
from apps.reviews.models import Review


class SeedContentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Контенту нужны фильмы — сначала базовое наполнение.
        call_command("seed_catalog", stdout=StringIO())
        call_command("seed_content", stdout=StringIO())

    def test_persons_created(self):
        self.assertEqual(Person.objects.count(), len(PERSONS))

    def test_credits_linked_with_roles_and_characters(self):
        title = Title.objects.get(slug="nachalo-2010")
        roles = set(title.participations.values_list("role", flat=True))

        self.assertIn(Participation.Role.DIRECTOR, roles)
        self.assertIn(Participation.Role.ACTOR, roles)
        # Имя персонажа должно сохраниться — это то, ради чего заведена модель.
        lead = title.participations.get(person__slug="leonardo-dikaprio")
        self.assertEqual(lead.character, "Дом Кобб")

    def test_person_has_filmography_across_titles(self):
        """Смысл единой модели персоны: один актёр — во многих фильмах."""
        mcconaughey = Person.objects.get(slug="mettyu-makkonakhi")
        self.assertGreaterEqual(mcconaughey.titles.count(), 2)

    def test_collections_published_with_items(self):
        self.assertEqual(Collection.objects.published().count(), len(COLLECTIONS))

        collection = Collection.objects.get(slug="umnaya-fantastika")
        self.assertTrue(collection.is_featured)
        self.assertGreater(collection.items.count(), 0)

    def test_reviews_create_real_ratings(self):
        title = Title.objects.get(slug="vo-vse-tyazhkie-2008")
        title.refresh_from_db()

        expected = len(REVIEWS["vo-vse-tyazhkie-2008"])
        self.assertEqual(title.rating_count, expected)
        self.assertIsNotNone(title.rating_average)
        self.assertGreater(float(title.rating_average), 0)

    def test_related_titles_set(self):
        title = Title.objects.get(slug="nachalo-2010")
        related_slugs = set(title.related_titles.values_list("slug", flat=True))
        self.assertIn("interstellar-2014", related_slugs)

    def test_running_twice_does_not_duplicate(self):
        call_command("seed_content", stdout=StringIO())

        self.assertEqual(Person.objects.count(), len(PERSONS))
        self.assertEqual(Collection.objects.count(), len(COLLECTIONS))
        # Отзывы: один зритель — один отзыв на фильм, повтор не плодит вторые.
        total_reviews = sum(len(reviews) for reviews in REVIEWS.values())
        self.assertEqual(Review.objects.count(), total_reviews)

    def test_credits_count_matches_seed(self):
        expected = sum(len(credits) for credits in CREDITS.values())
        self.assertEqual(Participation.objects.count(), expected)

    def test_requires_catalog_first(self):
        Title.objects.all().delete()
        with self.assertRaises(CommandError) as error:
            call_command("seed_content", stdout=StringIO())
        self.assertIn("seed_catalog", str(error.exception))
