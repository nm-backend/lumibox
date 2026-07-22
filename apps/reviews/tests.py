from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Title
from apps.core.test_factories import create_review, create_title, create_user
from apps.reviews.models import Review


class ReviewModelTests(TestCase):
    def test_one_review_per_user_per_title(self):
        """Передумал — правь свой отзыв, а не пиши второй."""
        user = create_user()
        title = create_title()
        create_review(user=user, title=title)

        with self.assertRaises(IntegrityError):
            create_review(user=user, title=title)

    def test_same_user_can_review_different_titles(self):
        user = create_user()
        create_review(user=user, title=create_title())
        create_review(user=user, title=create_title())

        self.assertEqual(Review.objects.filter(user=user).count(), 2)

    def test_published_excludes_hidden(self):
        visible = create_review()
        hidden = create_review(status=Review.Status.HIDDEN)

        published = Review.objects.published()
        self.assertIn(visible, published)
        self.assertNotIn(hidden, published)


class ReviewViewTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.title = create_title()
        self.save_url = reverse("reviews:save", args=[self.title.slug])

    def test_guest_cannot_post_review(self):
        response = self.client.post(self.save_url, {"rating": 8, "text": "Отлично"})

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("users:login"), response.url)
        self.assertEqual(Review.objects.count(), 0)

    def test_user_can_post_review(self):
        self.client.force_login(self.user)
        self.client.post(self.save_url, {"rating": 9, "text": "Хорошо"})

        review = Review.objects.get(user=self.user, title=self.title)
        self.assertEqual(review.rating, 9)

    def test_second_post_updates_instead_of_duplicating(self):
        self.client.force_login(self.user)
        self.client.post(self.save_url, {"rating": 5, "text": "Так себе"})
        self.client.post(self.save_url, {"rating": 10, "text": "Передумал"})

        self.assertEqual(Review.objects.filter(user=self.user, title=self.title).count(), 1)
        self.assertEqual(Review.objects.get(user=self.user).rating, 10)

    def test_rating_outside_scale_rejected(self):
        self.client.force_login(self.user)
        for bad_rating in (0, 11, -3, "abc"):
            with self.subTest(rating=bad_rating):
                self.client.post(self.save_url, {"rating": bad_rating, "text": "x"})
        self.assertEqual(Review.objects.count(), 0)

    def test_cannot_review_draft(self):
        draft = create_title(status=Title.Status.DRAFT)
        self.client.force_login(self.user)

        response = self.client.post(reverse("reviews:save", args=[draft.slug]), {"rating": 8})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Review.objects.count(), 0)

    def test_user_can_delete_own_review(self):
        review = create_review(user=self.user, title=self.title)
        self.client.force_login(self.user)

        self.client.post(reverse("reviews:delete", args=[review.pk]))

        self.assertFalse(Review.objects.filter(pk=review.pk).exists())

    def test_user_cannot_delete_someone_elses_review(self):
        """Подставить чужой номер в адрес не должно ничего дать."""
        stranger_review = create_review(user=create_user(), title=self.title)
        self.client.force_login(self.user)

        response = self.client.post(reverse("reviews:delete", args=[stranger_review.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Review.objects.filter(pk=stranger_review.pk).exists())


class ReviewAdminActionTests(TestCase):
    """
    Массовые действия админки идут через queryset.update(), а он
    НЕ шлёт сигналы. Рейтинг должен обновляться всё равно.
    """

    def test_hiding_reviews_recalculates_rating(self):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        from apps.reviews.admin import ReviewAdmin

        title = create_title()
        create_review(title=title, rating=10)
        low = create_review(title=title, rating=2)

        title.refresh_from_db()
        self.assertEqual(float(title.rating_average), 6.0)

        admin = ReviewAdmin(Review, AdminSite())
        request = RequestFactory().post("/admin/")
        request.user = create_user(is_staff=True, is_superuser=True)
        # message_user требует подключённых сообщений — подменяем заглушкой.
        admin.message_user = lambda *args, **kwargs: None

        admin.hide(request, Review.objects.filter(pk=low.pk))

        title.refresh_from_db()
        self.assertEqual(float(title.rating_average), 10.0)
        self.assertEqual(title.rating_count, 1)
