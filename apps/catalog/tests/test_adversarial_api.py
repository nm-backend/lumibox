"""Adversarial regression tests for the REST API (apps.api.v1).

The API accepts arbitrary JSON types, identifiers and boundary values.
Every case in this module is expected to pass: malformed bodies return
controlled 4xx responses, moderation rules remain enforced, and no input
may turn into an unhandled server error.
"""

import json

from django.core.cache import cache
from django.test import TestCase

from apps.catalog.embeds import get_embed_url
from apps.catalog.models import Episode, Title
from apps.core.test_factories import create_title, create_user
from apps.reviews.models import Comment, Review

API_V1 = "/api/v1"


class RateTitleViewCrashTests(TestCase):
    """RateTitleView must answer 400, not 500, on malformed bodies."""

    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.client.force_login(self.user)
        self.title = create_title()
        self.url = f"{API_V1}/titles/{self.title.slug}/rate/"

    def test_rate_title_rejects_json_array_body(self):
        # ATTACK: JSON array body -> request.data is a list -> .get() crash
        response = self.client.post(
            self.url,
            data=json.dumps([1, 2, 3]),
            content_type="application/json",
            raise_request_exception=False,
        )
        self.assertEqual(
            response.status_code,
            400,
            "Malformed body (JSON array) must be a client error, not 500",
        )

    def test_rate_title_rejects_json_string_body(self):
        # ATTACK: JSON string body -> request.data is a str -> .get() crash
        response = self.client.post(
            self.url,
            data=json.dumps("9"),
            content_type="application/json",
            raise_request_exception=False,
        )
        self.assertEqual(
            response.status_code,
            400,
            "Malformed body (JSON string) must be a client error, not 500",
        )

    def test_rate_title_rejects_json_number_body(self):
        # ATTACK: bare JSON number body -> request.data is an int -> .get() crash
        response = self.client.post(
            self.url,
            data=json.dumps(9),
            content_type="application/json",
            raise_request_exception=False,
        )
        self.assertEqual(
            response.status_code,
            400,
            "Malformed body (JSON number) must be a client error, not 500",
        )

    def test_rate_title_rejects_boolean_rating(self):
        # ATTACK: bool passes isinstance(int) and the range check (True == 1)
        response = self.client.post(
            self.url,
            data=json.dumps({"rating": True}),
            content_type="application/json",
        )
        self.assertEqual(
            response.status_code,
            400,
            "Boolean rating must be rejected: it is not on the 1..10 scale",
        )
        self.assertFalse(
            Review.objects.filter(user=self.user, title=self.title).exists(),
            "A boolean rating must not create a review",
        )


class RateTitleViewBoundaryTests(TestCase):
    """Rating scale enforcement on the fast-rating endpoint."""

    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.client.force_login(self.user)
        self.title = create_title()
        self.url = f"{API_V1}/titles/{self.title.slug}/rate/"

    def post_rating(self, rating):
        return self.client.post(
            self.url,
            data=json.dumps({"rating": rating}),
            content_type="application/json",
        )

    def test_rate_title_rejects_zero(self):
        response = self.post_rating(0)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Review.objects.filter(title=self.title).exists())

    def test_rate_title_rejects_eleven(self):
        response = self.post_rating(11)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Review.objects.filter(title=self.title).exists())

    def test_rate_title_rejects_float(self):
        response = self.post_rating(9.5)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Review.objects.filter(title=self.title).exists())

    def test_rate_title_rejects_string(self):
        response = self.post_rating("9")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Review.objects.filter(title=self.title).exists())

    def test_rate_title_ok(self):
        response = self.post_rating(7)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Review.objects.get(title=self.title).rating, 7)

    def test_guest_rate_requires_login(self):
        self.client.logout()
        response = self.post_rating(7)
        self.assertEqual(response.status_code, 403)


class CommentApiModerationTests(TestCase):
    """Replies must not attach to moderated-away (hidden) comments."""

    def setUp(self):
        cache.clear()
        self.author = create_user()
        self.attacker = create_user()
        self.title = create_title()
        self.url = f"{API_V1}/titles/{self.title.slug}/comments/"

    def test_comment_reply_to_hidden_parent_rejected(self):
        # ATTACK: parent is hidden by moderation, reply via API is accepted
        hidden = Comment.objects.create(
            user=self.author, title=self.title, text="bad comment",
            status=Comment.Status.HIDDEN,
        )
        self.client.force_login(self.attacker)
        response = self.client.post(
            self.url,
            data=json.dumps({"text": "spam reply", "parent": hidden.pk}),
            content_type="application/json",
        )
        self.assertEqual(
            response.status_code,
            400,
            "Replying to a hidden comment must be rejected",
        )
        self.assertFalse(
            Comment.objects.filter(
                user=self.attacker, title=self.title, parent=hidden
            ).exists(),
            "No published reply may hang under a hidden comment",
        )

    def test_comment_cross_title_parent_rejected(self):
        # ATTACK: parent belongs to another title; API must reject, not
        # silently create a root comment the client thinks is a reply
        other_title = create_title()
        foreign = Comment.objects.create(
            user=self.author, title=other_title, text="other thread"
        )
        self.client.force_login(self.attacker)
        response = self.client.post(
            self.url,
            data=json.dumps({"text": "reply", "parent": foreign.pk}),
            content_type="application/json",
        )
        self.assertEqual(
            response.status_code,
            400,
            "A parent from another title must be rejected, not silently dropped",
        )
        created = Comment.objects.filter(user=self.attacker, title=self.title).first()
        if created is not None:
            self.assertEqual(
                created.parent_id,
                foreign.pk,
                "If accepted, the reply must keep its requested parent",
            )

    def test_comment_reply_to_own_title_ok(self):
        root = Comment.objects.create(
            user=self.author, title=self.title, text="root"
        )
        self.client.force_login(self.attacker)
        response = self.client.post(
            self.url,
            data=json.dumps({"text": "answer", "parent": root.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["parent"], root.pk)


class CommentApiBoundaryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.client.force_login(self.user)
        self.title = create_title()
        self.url = f"{API_V1}/titles/{self.title.slug}/comments/"

    def test_comment_text_too_long_rejected(self):
        response = self.client.post(
            self.url,
            data=json.dumps({"text": "x" * 2001}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_comment_parent_not_found_rejected(self):
        response = self.client.post(
            self.url,
            data=json.dumps({"text": "x", "parent": 999999}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class WatchProgressBoundaryTests(TestCase):
    """Position/duration are stored into PositiveIntegerField columns."""

    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.client.force_login(self.user)
        self.title = create_title()
        self.episode = Episode.objects.create(
            title=self.title, season_number=1, episode_number=1
        )
        self.url = f"{API_V1}/titles/{self.title.slug}/watch/"

    def post_progress(self, payload):
        return self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_watch_progress_truncates_float_position(self):
        # ATTACK: 1.9 silently becomes 1 — the client's data is corrupted
        # ATTACK BLOCKED — защита сработала: serializer rejects fractional
        # position with 400.
        response = self.post_progress({"episode": self.episode.pk, "position": 1.9})
        self.assertEqual(
            response.status_code,
            400,
            "Fractional position must be rejected, not silently truncated",
        )

    def test_watch_progress_rejects_absurd_position(self):
        # ATTACK: position far beyond PositiveIntegerField range (2**31-1).
        # On SQLite it is stored; on PostgreSQL the INSERT would raise
        # DataError -> 500. Either way the API must reject it.
        response = self.post_progress({"episode": self.episode.pk, "position": 2**40})
        self.assertEqual(
            response.status_code,
            400,
            "Position beyond the column range must be rejected",
        )

    def test_watch_progress_rejects_negative_position(self):
        response = self.post_progress({"episode": self.episode.pk, "position": -5})
        self.assertEqual(response.status_code, 400)

    def test_watch_progress_episode_of_other_title(self):
        other = create_title()
        foreign_ep = Episode.objects.create(title=other, episode_number=1)
        response = self.post_progress({"episode": foreign_ep.pk})
        self.assertEqual(response.status_code, 404)

    def test_watch_progress_requires_episode_for_series(self):
        response = self.post_progress({"episode": None})
        self.assertEqual(response.status_code, 400)

    def test_watch_progress_rejects_array_body(self):
        response = self.client.post(
            self.url,
            data=json.dumps([1, 2]),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_watch_progress_ok(self):
        response = self.post_progress(
            {"episode": self.episode.pk, "position": 60, "duration": 3600}
        )
        self.assertEqual(response.status_code, 200)


class ReviewApiBoundaryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user()
        self.client.force_login(self.user)
        self.title = create_title()
        self.url = f"{API_V1}/titles/{self.title.slug}/reviews/"

    def post_review(self, payload):
        return self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_review_text_too_long_rejected(self):
        response = self.post_review({"rating": 8, "text": "x" * 2001})
        self.assertEqual(response.status_code, 400)

    def test_duplicate_review_rejected(self):
        self.post_review({"rating": 8, "text": "first"})
        response = self.post_review({"rating": 9, "text": "second"})
        self.assertEqual(response.status_code, 400)

    def test_author_and_title_set_by_server(self):
        # ATTACK: client must not be able to post on behalf of another user
        victim = create_user()
        response = self.post_review(
            {"rating": 8, "text": "x", "user": victim.pk, "title": self.title.pk}
        )
        self.assertEqual(response.status_code, 201)
        created = Review.objects.get(user=self.user)
        self.assertEqual(created.user_id, self.user.pk)


class TitleListApiRobustnessTests(TestCase):
    """Garbage in query params must never 500."""

    def setUp(self):
        cache.clear()
        self.title = create_title()
        self.url = f"{API_V1}/titles/"

    def test_list_page_garbage(self):
        response = self.client.get(self.url, {"page": "abc"})
        self.assertEqual(response.status_code, 404)

    def test_list_page_huge(self):
        # ATTACK BLOCKED — защита сработала: out-of-range page is 404
        response = self.client.get(self.url, {"page": 999999999})
        self.assertEqual(response.status_code, 404)

    def test_search_limit_garbage(self):
        response = self.client.get(f"{API_V1}/titles/search/", {"q": "ab", "limit": "abc"})
        self.assertEqual(response.status_code, 200)

    def test_search_limit_zero(self):
        response = self.client.get(f"{API_V1}/titles/search/", {"q": "ab", "limit": 0})
        self.assertEqual(response.status_code, 200)

    def test_filter_release_year_garbage(self):
        # ATTACK BLOCKED — защита сработала: invalid filter value is 400
        response = self.client.get(self.url, {"release_year": "abc"})
        self.assertEqual(response.status_code, 400)

    def test_ordering_garbage(self):
        response = self.client.get(self.url, {"ordering": "javascript:alert(1)"})
        self.assertEqual(response.status_code, 200)

    def test_slug_not_found(self):
        response = self.client.get(f"{API_V1}/titles/no-such-title/")
        self.assertEqual(response.status_code, 404)

    def test_draft_hidden_from_api(self):
        draft = create_title(status=Title.Status.DRAFT)
        response = self.client.get(f"{API_V1}/titles/{draft.slug}/")
        self.assertEqual(response.status_code, 404)


class EmbedValidationTests(TestCase):
    """get_embed_url must validate video IDs as strictly as youtube.py does."""

    def test_short_youtube_id_rejected(self):
        # ATTACK: youtube.py rejects IDs that are not exactly 11 chars,
        # but embeds._youtube builds an embed URL for any v= value
        embed = get_embed_url("https://www.youtube.com/watch?v=abc")
        self.assertIsNone(
            embed,
            "A 3-char video id is invalid on YouTube; a broken embed "
            "URL must not be produced (youtube.py validates it)",
        )

    def test_embed_rejects_unknown_host(self):
        self.assertIsNone(get_embed_url("https://evil.example.com/watch?v=abc"))
        self.assertIsNone(get_embed_url("javascript:alert(1)"))
        self.assertIsNone(get_embed_url("data:text/html,<script>alert(1)</script>"))

    def test_embed_rejects_protocol_relative(self):
        self.assertIsNone(get_embed_url("//www.youtube.com/watch?v=dQw4w9WgXcQ"))

    def test_embed_valid_youtube_id_ok(self):
        embed = get_embed_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(embed, "https://www.youtube.com/embed/dQw4w9WgXcQ")
