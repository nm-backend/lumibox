"""
Тесты для REST API v1.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Collection, CollectionItem, Country, Genre, Title
from apps.reviews.models import Review

User = get_user_model()


class TitleApiTests(TestCase):
    """Тесты API titles."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="api@test.com", username="apiuser", password="pass123"
        )
        cls.genre = Genre.objects.create(name="Драма", slug="drama")
        cls.country = Country.objects.create(name="США", slug="usa")
        cls.title = Title.objects.create(
            name="Тестовый фильм",
            slug="test-film",
            release_year=2024,
            status=Title.Status.PUBLISHED,
            description="Описание для теста.",
            duration_minutes=120,
        )
        cls.title.genres.add(cls.genre)
        cls.title.countries.add(cls.country)

    def test_list_titles(self):
        response = self.client.get("/api/v1/titles/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)

    def test_retrieve_title(self):
        response = self.client.get(f"/api/v1/titles/{self.title.slug}/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "Тестовый фильм")
        self.assertEqual(data["view_count"], 0)

    def test_search_titles(self):
        response = self.client.get("/api/v1/titles/?search=Тестовый")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)

    def test_filter_by_type(self):
        response = self.client.get("/api/v1/titles/?type=movie")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)

    def test_filter_by_genre(self):
        response = self.client.get("/api/v1/titles/?genres__slug=drama")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)

    def test_draft_not_in_api(self):
        Title.objects.create(
            name="Черновик", slug="draft", release_year=2024, status=Title.Status.DRAFT
        )
        response = self.client.get("/api/v1/titles/")
        data = response.json()
        self.assertEqual(data["count"], 1)  # Only published

    def test_similar_endpoint(self):
        response = self.client.get(f"/api/v1/titles/{self.title.slug}/similar/")
        self.assertEqual(response.status_code, 200)

    def test_favorite_requires_auth(self):
        response = self.client.post(f"/api/v1/titles/{self.title.slug}/favorite/")
        self.assertEqual(response.status_code, 403)

    def test_favorite_toggle(self):
        self.client.force_login(self.user)
        response = self.client.post(f"/api/v1/titles/{self.title.slug}/favorite/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["is_favorite"])

        response = self.client.post(f"/api/v1/titles/{self.title.slug}/favorite/")
        data = response.json()
        self.assertFalse(data["is_favorite"])

    def test_seasons_endpoint(self):
        response = self.client.get(f"/api/v1/titles/{self.title.slug}/seasons/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data, [])  # No seasons for a movie

    def test_ordering_by_rating(self):
        response = self.client.get("/api/v1/titles/?ordering=-rating_average")
        self.assertEqual(response.status_code, 200)


class GenreApiTests(TestCase):
    """Тесты API genres."""

    @classmethod
    def setUpTestData(cls):
        Genre.objects.create(name="Драма", slug="drama")
        Genre.objects.create(name="Комедия", slug="comedy")

    def test_list_genres(self):
        response = self.client.get("/api/v1/genres/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)

    def test_retrieve_genre(self):
        response = self.client.get("/api/v1/genres/drama/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "Драма")


class CountryApiTests(TestCase):
    """Тесты API countries."""

    @classmethod
    def setUpTestData(cls):
        Country.objects.create(name="США", slug="usa")

    def test_list_countries(self):
        response = self.client.get("/api/v1/countries/")
        self.assertEqual(response.status_code, 200)

    def test_retrieve_country(self):
        response = self.client.get("/api/v1/countries/usa/")
        self.assertEqual(response.status_code, 200)


class CollectionApiTests(TestCase):
    """Тесты API collections."""

    @classmethod
    def setUpTestData(cls):
        cls.title = Title.objects.create(
            name="T", slug="t", release_year=2024, status=Title.Status.PUBLISHED
        )
        cls.collection = Collection.objects.create(
            name="Тестовая", slug="test-col", is_published=True
        )
        CollectionItem.objects.create(collection=cls.collection, title=cls.title, order=1)

    def test_list_collections(self):
        response = self.client.get("/api/v1/collections/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)

    def test_collection_titles(self):
        response = self.client.get(f"/api/v1/collections/{self.collection.slug}/titles/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)


class ReviewApiTests(TestCase):
    """Тесты API reviews."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="review@test.com", username="reviewer", password="pass123"
        )
        cls.title = Title.objects.create(
            name="T", slug="t-review", release_year=2024, status=Title.Status.PUBLISHED
        )

    def test_list_reviews(self):
        Review.objects.create(user=self.user, title=self.title, rating=8, text="Хорошо")
        response = self.client.get(f"/api/v1/titles/{self.title.slug}/reviews/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)

    def test_create_review(self):
        self.client.force_login(self.user)
        response = self.client.post(
            f"/api/v1/titles/{self.title.slug}/reviews/",
            data={"rating": 9, "text": "Отличный фильм"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

    def test_create_review_requires_auth(self):
        response = self.client.post(
            f"/api/v1/titles/{self.title.slug}/reviews/",
            data={"rating": 9},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_duplicate_review_rejected(self):
        Review.objects.create(user=self.user, title=self.title, rating=8)
        self.client.force_login(self.user)
        response = self.client.post(
            f"/api/v1/titles/{self.title.slug}/reviews/",
            data={"rating": 7},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_update_own_review(self):
        review = Review.objects.create(user=self.user, title=self.title, rating=8)
        self.client.force_login(self.user)
        response = self.client.patch(
            f"/api/v1/titles/{self.title.slug}/reviews/{review.pk}/",
            data={"rating": 10},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

    def test_delete_own_review(self):
        review = Review.objects.create(user=self.user, title=self.title, rating=8)
        self.client.force_login(self.user)
        response = self.client.delete(
            f"/api/v1/titles/{self.title.slug}/reviews/{review.pk}/"
        )
        self.assertEqual(response.status_code, 204)

    def test_cannot_edit_others_review(self):
        other = User.objects.create_user(email="other@test.com", username="other", password="pass")
        review = Review.objects.create(user=other, title=self.title, rating=5)
        self.client.force_login(self.user)
        response = self.client.patch(
            f"/api/v1/titles/{self.title.slug}/reviews/{review.pk}/",
            data={"rating": 1},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)


class SearchAutocompleteTests(TestCase):
    """Тесты автокомплита поиска."""

    @classmethod
    def setUpTestData(cls):
        Title.objects.create(
            name="Начало", slug="nachalo", release_year=2010, status=Title.Status.PUBLISHED
        )
        Title.objects.create(
            name="Интерстеллар", slug="interstellar", release_year=2014, status=Title.Status.PUBLISHED
        )

    def test_short_query_returns_empty(self):
        response = self.client.get("/api/v1/search/autocomplete/?q=Н")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["suggestions"], [])

    def test_query_returns_results(self):
        response = self.client.get("/api/v1/search/autocomplete/?q=Нач")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["suggestions"]), 1)
        self.assertEqual(data["suggestions"][0]["name"], "Начало")

    def test_empty_query_returns_empty(self):
        response = self.client.get("/api/v1/search/autocomplete/?q=")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["suggestions"], [])

    def test_no_results(self):
        response = self.client.get("/api/v1/search/autocomplete/?q=НесуществующийФильм")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["suggestions"], [])

    def test_draft_not_in_suggestions(self):
        Title.objects.create(name="Черновик", slug="draft", release_year=2024, status=Title.Status.DRAFT)
        response = self.client.get("/api/v1/search/autocomplete/?q=Черн")
        data = response.json()
        self.assertEqual(data["suggestions"], [])


class ApiSchemaTests(TestCase):
    """Тесты OpenAPI schema."""

    def test_schema_endpoint(self):
        response = self.client.get("/api/schema/")
        self.assertEqual(response.status_code, 200)

    def test_swagger_ui(self):
        response = self.client.get("/api/docs/")
        self.assertEqual(response.status_code, 200)

    def test_redoc(self):
        response = self.client.get("/api/redoc/")
        self.assertEqual(response.status_code, 200)
