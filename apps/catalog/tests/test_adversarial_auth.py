"""Adversarial tests for authorization and access control.

Attack surface: cross-user actions (delete/edit someone else's review
or comment), guest access to write endpoints, logout via GET, account
abuse (duplicate emails, registration flooding).

All attacks here are blocked by existing defenses; the tests document
that the guards hold.
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Title
from apps.core.test_factories import create_title, create_user
from apps.reviews.models import Comment, Review

API_V1 = "/api/v1"


class GuestAccessTests(TestCase):
    """Guests must not be able to change anything."""

    def setUp(self):
        cache.clear()
        self.title = create_title()

    def test_guest_favorite_toggle_redirects_to_login(self):
        response = self.client.post(
            reverse("library:toggle_favorite", args=[self.title.slug])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_guest_watchlist_toggle_redirects_to_login(self):
        response = self.client.post(
            reverse("library:toggle_watchlist", args=[self.title.slug])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_guest_clear_history_redirects_to_login(self):
        response = self.client.post(reverse("library:clear_history"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_guest_review_post_redirects_to_login(self):
        response = self.client.post(
            reverse("reviews:save", args=[self.title.slug]),
            {"rating": 8, "text": "x"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_guest_comment_post_redirects_to_login(self):
        response = self.client.post(
            reverse("reviews:comment_add", args=[self.title.slug]),
            {"text": "x"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_guest_rate_api_forbidden(self):
        response = self.client.post(
            f"{API_V1}/titles/{self.title.slug}/rate/",
            data='{"rating": 7}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)


class CrossUserTests(TestCase):
    """User B must not be able to touch user A's content."""

    def setUp(self):
        cache.clear()
        self.author = create_user()
        self.attacker = create_user()
        self.title = create_title()
        self.review = Review.objects.create(
            user=self.author, title=self.title, rating=8, text="mine"
        )
        self.comment = Comment.objects.create(
            user=self.author, title=self.title, text="mine"
        )

    def test_web_review_delete_of_other_user(self):
        # ATTACK: pass the victim's review pk to the delete endpoint
        self.client.force_login(self.attacker)
        response = self.client.post(
            reverse("reviews:delete", args=[self.review.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Review.objects.filter(pk=self.review.pk).exists())

    def test_web_comment_delete_of_other_user(self):
        self.client.force_login(self.attacker)
        response = self.client.post(
            reverse("reviews:comment_delete", args=[self.comment.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Comment.objects.filter(pk=self.comment.pk).exists())

    def test_api_review_delete_of_other_user(self):
        self.client.force_login(self.attacker)
        response = self.client.delete(
            f"{API_V1}/titles/{self.title.slug}/reviews/{self.review.pk}/"
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Review.objects.filter(pk=self.review.pk).exists())

    def test_api_review_update_of_other_user(self):
        self.client.force_login(self.attacker)
        response = self.client.patch(
            f"{API_V1}/titles/{self.title.slug}/reviews/{self.review.pk}/",
            data='{"rating": 1}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Review.objects.get(pk=self.review.pk).rating, 8)

    def test_api_comment_delete_of_other_user(self):
        self.client.force_login(self.attacker)
        response = self.client.delete(
            f"{API_V1}/titles/{self.title.slug}/comments/{self.comment.pk}/"
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Comment.objects.filter(pk=self.comment.pk).exists())

    def test_api_review_author_can_delete_own(self):
        self.client.force_login(self.author)
        response = self.client.delete(
            f"{API_V1}/titles/{self.title.slug}/reviews/{self.review.pk}/"
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Review.objects.filter(pk=self.review.pk).exists())


class SessionAndAccountTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_logout_get_returns_405(self):
        # ATTACK: a forged link must not be able to log the victim out
        user = create_user()
        self.client.force_login(user)
        response = self.client.get(reverse("users:logout"))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(
            self.client.session.get("_auth_user_id"),
            "GET /logout/ must not end the session",
        )

    def test_logout_post_works(self):
        user = create_user()
        self.client.force_login(user)
        response = self.client.post(reverse("users:logout"))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_register_duplicate_email_rejected(self):
        create_user(email="dup@example.com", username="first")
        response = self.client.post(
            reverse("users:register"),
            {
                "email": "DUP@example.com",
                "username": "second",
                "password1": "Str0ng-pass-123",
                "password2": "Str0ng-pass-123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "уже зарегистрирован")

    def test_register_email_case_insensitive(self):
        # ATTACK: register the same mailbox with different case
        # ATTACK BLOCKED — защита сработала: managers.py lowercases email,
        # forms.py clean_email rejects duplicates.
        create_user(email="Case@Test.com", username="first")
        response = self.client.post(
            reverse("users:register"),
            {
                "email": "case@test.com",
                "username": "second",
                "password1": "Str0ng-pass-123",
                "password2": "Str0ng-pass-123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "уже зарегистрирован")

    def test_register_rate_limit_429_after_ten_attempts(self):
        # ATTACK: flood registration — 11th attempt in an hour must be 429
        for i in range(10):
            response = self.client.post(
                reverse("users:register"),
                {
                    "email": f"flood{i}@example.com",
                    "username": f"flood{i}",
                    "password1": "Str0ng-pass-123",
                    "password2": "Str0ng-pass-123",
                },
            )
            self.assertNotEqual(response.status_code, 429)
        response = self.client.post(
            reverse("users:register"),
            {
                "email": "flood11@example.com",
                "username": "flood11",
                "password1": "Str0ng-pass-123",
                "password2": "Str0ng-pass-123",
            },
        )
        self.assertEqual(response.status_code, 429)


class DraftAccessTests(TestCase):
    """Draft titles must be invisible to every endpoint."""

    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.client.force_login(self.user)
        self.draft = create_title(status=Title.Status.DRAFT)

    def test_draft_page_404(self):
        response = self.client.get(
            reverse("catalog:title_detail", args=[self.draft.slug])
        )
        self.assertEqual(response.status_code, 404)

    def test_draft_review_post_404(self):
        response = self.client.post(
            reverse("reviews:save", args=[self.draft.slug]),
            {"rating": 8, "text": "x"},
        )
        self.assertEqual(response.status_code, 404)

    def test_draft_favorite_toggle_404(self):
        response = self.client.post(
            reverse("library:toggle_favorite", args=[self.draft.slug])
        )
        self.assertEqual(response.status_code, 404)

    def test_draft_rate_api_404(self):
        response = self.client.post(
            f"{API_V1}/titles/{self.draft.slug}/rate/",
            data='{"rating": 7}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
