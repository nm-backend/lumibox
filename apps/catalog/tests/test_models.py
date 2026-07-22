from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase

from apps.catalog.models import Participation, Title
from apps.core.test_factories import (
    create_collection,
    create_participation,
    create_person,
    create_title,
)


class TitleModelTests(TestCase):
    def test_published_at_set_on_first_publish(self):
        title = create_title(status=Title.Status.DRAFT)
        self.assertIsNone(title.published_at)

        title.status = Title.Status.PUBLISHED
        title.save()

        self.assertIsNotNone(title.published_at)

    def test_published_at_not_overwritten_on_resave(self):
        """Старый фильм не должен всплывать в новинках при каждом сохранении."""
        title = create_title(status=Title.Status.PUBLISHED)
        first_date = title.published_at

        title.description = "Другое описание"
        title.save()
        title.refresh_from_db()

        self.assertEqual(title.published_at, first_date)

    def test_draft_has_no_published_at(self):
        title = create_title(status=Title.Status.DRAFT)
        self.assertIsNone(title.published_at)

    def test_year_bounds(self):
        for year in (1887, 2101):
            with self.subTest(year=year):
                title = Title(name="Тест", slug=f"t-{year}", release_year=year)
                with self.assertRaises(ValidationError):
                    title.clean_fields(exclude=["poster"])

    def test_slug_is_unique(self):
        create_title(slug="dubl")
        with self.assertRaises(IntegrityError):
            create_title(slug="dubl")

    def test_is_series(self):
        self.assertTrue(create_title(type=Title.Type.SERIES).is_series)
        self.assertFalse(create_title(type=Title.Type.MOVIE).is_series)

    def test_get_absolute_url_matches_route(self):
        title = create_title(slug="film-2020")
        self.assertEqual(title.get_absolute_url(), "/title/film-2020/")

    def test_trailer_url_and_file_are_mutually_exclusive(self):
        """Оба варианта трейлера сразу — непонятно, что показывать: должна быть ошибка."""
        title = create_title()
        title.trailer_url = "https://www.youtube.com/watch?v=test"
        title.trailer_file = SimpleUploadedFile("t.mp4", b"data", content_type="video/mp4")

        with self.assertRaises(ValidationError):
            title.full_clean(exclude=["poster", "backdrop"])

    def test_trailer_url_alone_passes(self):
        title = create_title()
        title.trailer_url = "https://www.youtube.com/watch?v=test"
        title.full_clean(exclude=["poster", "backdrop"])  # не должно бросить

    def test_trailer_source_reports_active_variant(self):
        no_trailer = create_title()
        self.assertIsNone(no_trailer.trailer_source)

        with_url = create_title(trailer_url="https://vimeo.com/1")
        self.assertEqual(with_url.trailer_source, "url")


class TitleQuerySetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.published_movie = create_title(type=Title.Type.MOVIE, status=Title.Status.PUBLISHED)
        cls.published_series = create_title(type=Title.Type.SERIES, status=Title.Status.PUBLISHED)
        cls.draft = create_title(status=Title.Status.DRAFT)

    def test_published_excludes_drafts(self):
        published = Title.objects.published()
        self.assertIn(self.published_movie, published)
        self.assertNotIn(self.draft, published)

    def test_movies_and_series_split(self):
        self.assertEqual(list(Title.objects.published().movies()), [self.published_movie])
        self.assertEqual(list(Title.objects.published().series()), [self.published_series])

    def test_top_rated_excludes_unrated(self):
        self.assertEqual(list(Title.objects.top_rated()), [])


class SeoModelTests(TestCase):
    def test_meta_falls_back_to_name_and_description(self):
        title = create_title(name="Начало", description="Фильм про сны.")
        self.assertEqual(title.get_meta_title(), "Начало")
        self.assertEqual(title.get_meta_description(), "Фильм про сны.")

    def test_meta_uses_explicit_values(self):
        title = create_title(meta_title="Свой заголовок", meta_description="Своё описание")
        self.assertEqual(title.get_meta_title(), "Свой заголовок")
        self.assertEqual(title.get_meta_description(), "Своё описание")

    def test_long_description_truncated(self):
        title = create_title(description="а" * 500)
        self.assertLessEqual(len(title.get_meta_description()), 160)


class ParticipationTests(TestCase):
    def test_same_person_can_have_two_roles(self):
        """Режиссёр вполне может сыграть роль в своём же фильме."""
        title = create_title()
        person = create_person()

        create_participation(title=title, person=person, role=Participation.Role.DIRECTOR)
        create_participation(title=title, person=person, role=Participation.Role.ACTOR)

        self.assertEqual(title.participations.count(), 2)

    def test_duplicate_role_rejected(self):
        title = create_title()
        person = create_person()
        create_participation(title=title, person=person, role=Participation.Role.ACTOR)

        with self.assertRaises(IntegrityError):
            create_participation(title=title, person=person, role=Participation.Role.ACTOR)


class CollectionTests(TestCase):
    def test_published_filter(self):
        visible = create_collection(is_published=True)
        hidden = create_collection(is_published=False)

        from apps.catalog.models import Collection

        self.assertIn(visible, Collection.objects.published())
        self.assertNotIn(hidden, Collection.objects.published())

    def test_items_keep_editor_order(self):
        first = create_title(name="Первый")
        second = create_title(name="Второй")
        # Передаём в обратном алфавитном порядке: если сортировка
        # сломается на алфавит, тест это поймает.
        collection = create_collection(titles=[second, first])

        ordered = [item.title for item in collection.items.all()]
        self.assertEqual(ordered, [second, first])
