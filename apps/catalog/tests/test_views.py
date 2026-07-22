from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.catalog.models import Title
from apps.core.test_factories import (
    create_collection,
    create_country,
    create_genre,
    create_title,
    create_user,
)


class HomeViewTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_home_renders(self):
        create_title()
        response = self.client.get(reverse("catalog:home"))
        self.assertEqual(response.status_code, 200)

    def test_home_shows_no_drafts(self):
        create_title(name="Опубликован")
        create_title(name="Черновик", status=Title.Status.DRAFT)

        response = self.client.get(reverse("catalog:home"))

        self.assertContains(response, "Опубликован")
        self.assertNotContains(response, "Черновик")

    def test_recommendations_hidden_from_guest(self):
        create_title()
        response = self.client.get(reverse("catalog:home"))
        self.assertNotContains(response, "Вам может понравиться")

    def test_recommendations_shown_to_user(self):
        create_title()
        self.client.force_login(create_user())
        response = self.client.get(reverse("catalog:home"))
        self.assertContains(response, "Вам может понравиться")


class TitleListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.drama = create_genre(name="Драма", slug="drama")
        cls.japan = create_country(name="Япония", slug="japan")

        cls.movie = create_title(
            name="Тестовый фильм",
            type=Title.Type.MOVIE,
            release_year=2019,
            genres=[cls.drama],
            countries=[cls.japan],
        )
        cls.series = create_title(name="Тестовый сериал", type=Title.Type.SERIES, release_year=2021)
        cls.draft = create_title(name="Черновик", status=Title.Status.DRAFT)

    def test_catalog_hides_drafts(self):
        response = self.client.get(reverse("catalog:title_list"))
        self.assertNotContains(response, "Черновик")

    def test_filter_by_type(self):
        response = self.client.get(reverse("catalog:title_list"), {"type": "series"})
        self.assertContains(response, "Тестовый сериал")
        self.assertNotContains(response, "Тестовый фильм")

    def test_filter_by_genre(self):
        response = self.client.get(reverse("catalog:title_list"), {"genre": "drama"})
        self.assertContains(response, "Тестовый фильм")
        self.assertNotContains(response, "Тестовый сериал")

    def test_filter_by_year(self):
        response = self.client.get(reverse("catalog:title_list"), {"year": "2019"})
        self.assertContains(response, "Тестовый фильм")
        self.assertNotContains(response, "Тестовый сериал")

    def test_search_by_name(self):
        response = self.client.get(reverse("catalog:title_list"), {"q": "сериал"})
        self.assertContains(response, "Тестовый сериал")
        self.assertNotContains(response, "Тестовый фильм")

    def test_garbage_filter_does_not_break_catalog(self):
        """Мусор в адресе должен игнорироваться, а не ронять страницу."""
        for params in [
            {"type": "'; DROP TABLE catalog_title; --"},
            {"genre": "нет-такого"},
            {"year": "не-год"},
            {"sort": "; DELETE FROM"},
        ]:
            with self.subTest(params=params):
                response = self.client.get(reverse("catalog:title_list"), params)
                self.assertEqual(response.status_code, 200)

    def test_xss_in_name_is_escaped(self):
        create_title(name='<script>alert("xss")</script>')
        response = self.client.get(reverse("catalog:title_list"))

        self.assertNotContains(response, "<script>alert")
        self.assertContains(response, "&lt;script&gt;")

    def test_catalog_query_count_does_not_grow_with_rows(self):
        """
        Защита от N+1: число запросов не должно зависеть от числа карточек.

        Сравниваем два замера вместо проверки на конкретное число —
        точное количество меняется при любой правке вьюхи, и такой тест
        падал бы от безобидных изменений, ничего при этом не сторожа.
        """
        cache.clear()
        for _ in range(3):
            create_title(genres=[self.drama], countries=[self.japan])

        with CaptureQueriesContext(connection) as few:
            self.client.get(reverse("catalog:title_list"))

        cache.clear()
        for _ in range(15):
            create_title(genres=[self.drama], countries=[self.japan])

        with CaptureQueriesContext(connection) as many:
            self.client.get(reverse("catalog:title_list"))

        self.assertEqual(
            len(few.captured_queries),
            len(many.captured_queries),
            "Число запросов выросло вместе с числом карточек — где-то N+1",
        )

    def test_year_choices_cached_between_requests(self):
        """Список годов не должен запрашиваться заново на каждой загрузке."""
        cache.clear()
        self.client.get(reverse("catalog:title_list"))

        with CaptureQueriesContext(connection) as second:
            self.client.get(reverse("catalog:title_list"))

        year_queries = [q for q in second.captured_queries if "DISTINCT" in q["sql"] and "release_year" in q["sql"]]
        self.assertEqual(year_queries, [])


class TitleDetailViewTests(TestCase):
    def test_published_title_opens(self):
        title = create_title()
        response = self.client.get(title.get_absolute_url())
        self.assertEqual(response.status_code, 200)

    def test_draft_returns_404(self):
        draft = create_title(status=Title.Status.DRAFT)
        response = self.client.get(draft.get_absolute_url())
        self.assertEqual(response.status_code, 404)

    def test_view_recorded_for_logged_in_user(self):
        from apps.library.models import WatchHistory

        user = create_user()
        title = create_title()
        self.client.force_login(user)

        self.client.get(title.get_absolute_url())

        self.assertTrue(WatchHistory.objects.filter(user=user, title=title).exists())

    def test_guest_view_not_recorded(self):
        from apps.library.models import WatchHistory

        self.client.get(create_title().get_absolute_url())
        self.assertEqual(WatchHistory.objects.count(), 0)


class ReferencePagesTests(TestCase):
    def test_genre_page_lists_its_titles(self):
        genre = create_genre(name="Драма", slug="drama")
        create_title(name="Наш фильм", genres=[genre])
        create_title(name="Чужой фильм")

        response = self.client.get(reverse("catalog:genre_titles", args=["drama"]))

        self.assertContains(response, "Наш фильм")
        self.assertNotContains(response, "Чужой фильм")

    def test_unknown_genre_returns_404(self):
        response = self.client.get(reverse("catalog:genre_titles", args=["net-takogo"]))
        self.assertEqual(response.status_code, 404)

    def test_empty_genres_hidden_from_list(self):
        """Ссылка на жанр без фильмов ведёт посетителя в тупик."""
        create_genre(name="Пустой жанр", slug="empty")
        used = create_genre(name="Живой жанр", slug="alive")
        create_title(genres=[used])

        response = self.client.get(reverse("catalog:genre_list"))

        self.assertContains(response, "Живой жанр")
        self.assertNotContains(response, "Пустой жанр")


class CollectionViewTests(TestCase):
    def test_published_collection_opens(self):
        collection = create_collection(titles=[create_title()])
        response = self.client.get(collection.get_absolute_url())
        self.assertEqual(response.status_code, 200)

    def test_unpublished_collection_returns_404(self):
        collection = create_collection(is_published=False)
        response = self.client.get(collection.get_absolute_url())
        self.assertEqual(response.status_code, 404)
