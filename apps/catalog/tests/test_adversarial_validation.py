"""Adversarial validation tests.

Attack surface: out-of-range and malformed values reaching the
business layer — rating 0/11, oversized texts, garbage pagination and
filter parameters. Every invalid input must be rejected with 4xx, never
crash the view (500) and never mutate state.

Attacks on the API rate endpoint are real bugs; the rest are blocked.
"""

import json

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.core.test_factories import create_title, create_user
from apps.reviews.models import Review

API_V1 = "/api/v1"


class RateValidationTests(TestCase):
    """Web and API rating must reject out-of-range values."""

    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.client.force_login(self.user)
        self.title = create_title()

    def test_api_rating_zero_rejected(self):
        response = self.client.post(
            f"{API_V1}/titles/{self.title.slug}/rate/",
            data='{"rating": 0}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.title.reviews.count(), 0)

    def test_api_rating_eleven_rejected(self):
        response = self.client.post(
            f"{API_V1}/titles/{self.title.slug}/rate/",
            data='{"rating": 11}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.title.reviews.count(), 0)

    def test_web_rating_zero_rejected(self):
        # ATTACK BLOCKED — защита сработала: form rejects with 400
        response = self.client.post(
            reverse("reviews:save", args=[self.title.slug]),
            {"rating": 0, "text": "плохо"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.title.reviews.count(), 0)

    def test_web_rating_eleven_rejected(self):
        # ATTACK BLOCKED — защита сработала: form rejects with 400
        response = self.client.post(
            reverse("reviews:save", args=[self.title.slug]),
            {"rating": 11, "text": "отлично"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.title.reviews.count(), 0)

    def test_web_rating_ten_accepted(self):
        response = self.client.post(
            reverse("reviews:save", args=[self.title.slug]),
            {"rating": 10, "text": "топ"},
        )
        self.assertIn(response.status_code, (200, 302))
        self.assertEqual(self.title.reviews.count(), 1)

    def test_web_rating_garbage_rejected(self):
        # ATTACK BLOCKED — защита сработала: form rejects with 400
        response = self.client.post(
            reverse("reviews:save", args=[self.title.slug]),
            {"rating": "отлично", "text": "текст"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.title.reviews.count(), 0)


class TextLengthValidationTests(TestCase):
    """Oversized texts must be cut off with a validation error."""

    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.client.force_login(self.user)
        self.title = create_title()

    def test_web_review_text_2001_rejected(self):
        # ATTACK BLOCKED — защита сработала: form rejects with 400
        response = self.client.post(
            reverse("reviews:save", args=[self.title.slug]),
            {"rating": 8, "text": "x" * 2001},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.title.reviews.count(), 0)

    def test_web_comment_text_2001_rejected(self):
        # ATTACK BLOCKED — защита сработала: form rejects with 400
        response = self.client.post(
            reverse("reviews:comment_add", args=[self.title.slug]),
            {"text": "x" * 2001},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.title.comments.count(), 0)

    def test_api_review_text_2001_rejected(self):
        response = self.client.post(
            f"{API_V1}/titles/{self.title.slug}/reviews/",
            data=json.dumps({"rating": 8, "text": "x" * 2001}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.title.reviews.count(), 0)


class QueryParamRobustnessTests(TestCase):
    """Garbage query params must never produce 500."""

    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.client.force_login(self.user)
        self.title = create_title()
        self.url = reverse("catalog:title_list")

    def test_page_garbage(self):
        # ATTACK BLOCKED — защита сработала: invalid page is 404
        response = self.client.get(self.url, {"page": "abc"})
        self.assertEqual(response.status_code, 404)

    def test_sort_garbage(self):
        response = self.client.get(self.url, {"sort": "javascript:alert(1)"})
        self.assertEqual(response.status_code, 200)

    def test_year_garbage(self):
        response = self.client.get(self.url, {"year": "abc"})
        self.assertEqual(response.status_code, 200)

    def test_search_q_whitespace_only(self):
        response = self.client.get(
            reverse("catalog:search"), {"q": "   "}
        )
        self.assertEqual(response.status_code, 200)

    def test_review_rating_float_truncated_not_stored(self):
        # Fractional rating through the API serializer: 7.5 must not
        # become 7 in the database.
        response = self.client.post(
            f"{API_V1}/titles/{self.title.slug}/rate/",
            data='{"rating": 7.5}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.title.reviews.count(), 0)


class ReviewDedupTests(TestCase):
    """A user must not be able to stack reviews on one title."""

    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.client.force_login(self.user)
        self.title = create_title()

    def test_duplicate_web_review_updates_not_duplicates(self):
        self.client.post(
            reverse("reviews:save", args=[self.title.slug]),
            {"rating": 8, "text": "первый"},
        )
        self.client.post(
            reverse("reviews:save", args=[self.title.slug]),
            {"rating": 5, "text": "второй"},
        )
        reviews = Review.objects.filter(title=self.title, user=self.user)
        self.assertEqual(reviews.count(), 1)
        self.assertEqual(reviews.get().rating, 5)
