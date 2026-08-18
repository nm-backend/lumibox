"""Adversarial XSS tests.

Attack surface: stored XSS through user-editable strings (title names,
review/comment text, usernames, bios, episode names) and reflected XSS
through the search query. Every payload must come back escaped or not
at all — both in HTML context and inside the JSON-LD script block.

All attacks are expected to be blocked by template auto-escaping and
escapejs; a failure here is a real XSS vulnerability.
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Episode, Title
from apps.core.test_factories import create_genre, create_title, create_user
from apps.reviews.models import Comment, Review

SCRIPT_PAYLOAD = '<script>alert(1)</script>'
ATTR_PAYLOAD = '" autofocus onfocus="alert(1)'
IMPORTANT_PAYLOAD = '<b>bold</b>'


def _html(response):
    return response.content.decode("utf-8", errors="replace")


class StoredXssTests(TestCase):
    """User-controlled strings must never hit the page unescaped."""

    def setUp(self):
        cache.clear()

    def test_title_name_in_detail_page_escaped(self):
        title = create_title(name="Фильм " + SCRIPT_PAYLOAD)
        response = self.client.get(
            reverse("catalog:title_detail", args=[title.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SCRIPT_PAYLOAD, _html(response))

    def test_title_name_in_jsonld_cannot_break_out(self):
        title = create_title(name="Фильм </script>" + SCRIPT_PAYLOAD)
        response = self.client.get(
            reverse("catalog:title_detail", args=[title.slug])
        )
        html = _html(response)
        self.assertNotIn("</script>" + SCRIPT_PAYLOAD, html)
        self.assertNotIn("</script><script>", html)

    def test_title_name_in_catalog_card_escaped(self):
        create_title(name="Фильм " + IMPORTANT_PAYLOAD)
        response = self.client.get(reverse("catalog:title_list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(IMPORTANT_PAYLOAD, _html(response))

    def test_review_text_escaped(self):
        title = create_title()
        review = Review.objects.create(
            user=create_user(),
            title=title,
            rating=8,
            text="Отзыв " + SCRIPT_PAYLOAD,
        )
        response = self.client.get(
            reverse("catalog:title_detail", args=[title.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SCRIPT_PAYLOAD, _html(response))
        self.assertTrue(Review.objects.filter(pk=review.pk).exists())

    def test_comment_text_escaped(self):
        title = create_title()
        comment = Comment.objects.create(
            user=create_user(),
            title=title,
            text="Комментарий " + SCRIPT_PAYLOAD,
        )
        response = self.client.get(
            reverse("catalog:title_detail", args=[title.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SCRIPT_PAYLOAD, _html(response))
        self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())

    def test_username_escaped_on_profile_page(self):
        user = create_user(username="Хакер " + SCRIPT_PAYLOAD)
        self.client.force_login(user)
        response = self.client.get(reverse("users:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SCRIPT_PAYLOAD, _html(response))

    def test_bio_escaped_on_profile_page(self):
        user = create_user(username="Био")
        user.bio = "Люблю " + SCRIPT_PAYLOAD
        user.save(update_fields=["bio"])
        self.client.force_login(user)
        response = self.client.get(reverse("users:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SCRIPT_PAYLOAD, _html(response))

    def test_episode_name_escaped(self):
        title = create_title()
        episode = Episode.objects.create(
            title=title,
            season_number=1,
            episode_number=1,
            name="Серия " + SCRIPT_PAYLOAD,
            duration_minutes=45,
        )
        response = self.client.get(
            reverse("catalog:title_detail", args=[title.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SCRIPT_PAYLOAD, _html(response))
        self.assertTrue(Episode.objects.filter(pk=episode.pk).exists())

    def test_genre_name_escaped_on_genre_page(self):
        genre = create_genre(name="Ужасы " + IMPORTANT_PAYLOAD)
        create_title(genres=[genre])
        response = self.client.get(
            reverse("catalog:genre_titles", args=[genre.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(IMPORTANT_PAYLOAD, _html(response))

    def test_title_name_escaped_in_og_meta(self):
        title = create_title(name="Фильм " + ATTR_PAYLOAD)
        response = self.client.get(
            reverse("catalog:title_detail", args=[title.slug])
        )
        html = _html(response)
        self.assertNotIn('onfocus="alert(1)', html)


class ReflectedXssTests(TestCase):
    """Query strings must never be echoed back unescaped."""

    def setUp(self):
        cache.clear()

    def test_search_query_script_escaped(self):
        response = self.client.get(
            reverse("catalog:search"), {"q": SCRIPT_PAYLOAD}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SCRIPT_PAYLOAD, _html(response))

    def test_search_query_attribute_breakout_escaped(self):
        response = self.client.get(
            reverse("catalog:search"), {"q": ATTR_PAYLOAD}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('onfocus="alert(1)', _html(response))

    def test_order_garbage_does_not_leak_into_page(self):
        response = self.client.get(
            reverse("catalog:title_list"),
            {"ordering": "javascript:alert(1)"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("javascript:alert", _html(response))


class ApiJsonXssTests(TestCase):
    """API responses are JSON; any HTML in data is data, not markup."""

    def setUp(self):
        cache.clear()

    def test_title_detail_json_escaped_marker_absent(self):
        title = Title.objects.create(
            name="Фильм " + SCRIPT_PAYLOAD,
            slug="xss-title",
            release_year=2020,
            status=Title.Status.PUBLISHED,
        )
        response = self.client.get(
            reverse("catalog:title_detail", args=[title.slug])
        )
        html = _html(response)
        self.assertNotIn("<script>alert", html)
