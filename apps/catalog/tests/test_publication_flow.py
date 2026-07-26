"""Full publication flow test — from draft to published and back, with cache verification.

Tests the complete publication lifecycle including:
- Admin publish/unpublish actions clearing all relevant caches
- Content visibility on title detail page, catalog, and search
- Proper cache invalidation so unpublished titles disappear
"""
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Country, Genre, Participation, Person, Title
from apps.core.test_factories import create_user

# Cyrillic text encoded to bytes for reliable comparison
TITLE_NAME = "Полный Цикл"
TITLE_NAME_ENCODED = TITLE_NAME.encode("utf-8")
DIRECTOR_NAME = "Режиссёр Тестов"
DIRECTOR_NAME_ENCODED = DIRECTOR_NAME.encode("utf-8")
CHARACTER_NAME = "Главный герой"
CHARACTER_NAME_ENCODED = CHARACTER_NAME.encode("utf-8")

# Model status choices
STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"


def _action_url() -> str:
    """Return the changelist URL for running admin actions."""
    return reverse("admin:catalog_title_changelist")


class PublicationFlowTests(TestCase):
    """End-to-end test: draft → publish → verify caches → unpublish → gone."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = create_user(is_superuser=True, is_staff=True)
        cls.genre = Genre.objects.create(name="Драма", slug="drama")
        cls.country = Country.objects.create(name="Россия", slug="russia")
        cls.director = Person.objects.create(
            name=DIRECTOR_NAME, slug="dir-testov"
        )
        cls.actor = Person.objects.create(
            name="Актёр Тестов", slug="actor-testov"
        )
        # Draft title — not published initially
        cls.title = Title.objects.create(
            name=TITLE_NAME,
            original_name="Full Cycle",
            slug="polnyj-cikl",
            release_year=2025,
            status=STATUS_DRAFT,
        )
        cls.title.genres.add(cls.genre)
        cls.title.countries.add(cls.country)
        Participation.objects.create(
            title=cls.title,
            person=cls.director,
            role="director",
        )
        Participation.objects.create(
            title=cls.title,
            person=cls.actor,
            role="actor",
            character=CHARACTER_NAME,
        )

    def setUp(self):
        cache.clear()
        self.client.force_login(self.admin_user)

    def tearDown(self):
        cache.clear()

    # ------------------------------------------------------------------
    # Helpers — use admin actions (changelist POST, not the change form
    # with inline formsets) which are simpler and more reliable.
    # ------------------------------------------------------------------

    def _run_admin_action(self, action: str) -> bool:
        """Run an admin action on the test title via the changelist."""
        changelist_url = _action_url()
        data = {
            "action": action,
            "_selected_action": [str(self.title.pk)],
        }
        response = self.client.post(changelist_url, data, follow=False)
        # Django admin shows a confirmation page for intermediate actions.
        # The publish/unpublish actions apply immediately (no confirmation
        # needed since they use @admin.action without a confirmation page).
        # If the action needs confirmation, the user posts "post=yes".
        # Check for both direct redirect and confirmation + follow-up.
        if response.status_code == 302:
            return True
        # If we got the confirmation page (200), confirm it.
        # Some Django actions show a confirmation page with name="post".
        # If we got one, confirm it.
        if response.status_code == 200 and b'name="post"' in response.content:
            data["post"] = "yes"
            response = self.client.post(changelist_url, data, follow=False)
            return response.status_code == 302
        return False

    def _publish(self) -> bool:
        """Publish title via admin 'publish' action."""
        return self._run_admin_action("publish")

    def _unpublish(self) -> bool:
        """Unpublish title via admin 'unpublish' action."""
        return self._run_admin_action("unpublish")

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_draft_is_not_visible_anywhere(self):
        """A draft (status=draft) must not appear anywhere."""
        with self.subTest("страница фильма — 404"):
            response = self.client.get(self.title.get_absolute_url())
            self.assertEqual(response.status_code, 404)

        with self.subTest("нет в каталоге"):
            response = self.client.get(reverse("catalog:title_list"))
            self.assertNotIn(TITLE_NAME_ENCODED, response.content)

        with self.subTest("не находится поиском"):
            for query in ("Полный", "Full Cycle"):
                found = self.client.get(
                    reverse("catalog:title_list"), {"q": query}
                )
                self.assertNotIn(TITLE_NAME_ENCODED, found.content)

    def test_publish_makes_title_visible(self):
        """Publishing via admin action must make the title visible and
        clear all relevant caches."""
        # ---- Act: publish via admin action ----
        self.assertTrue(self._publish())
        self.title.refresh_from_db()
        self.assertEqual(self.title.status, STATUS_PUBLISHED)

        # ---- Assert: visible everywhere ----
        with self.subTest("страница фильма открывается"):
            page = self.client.get(self.title.get_absolute_url())
            self.assertEqual(page.status_code, 200)
            self.assertIn(TITLE_NAME_ENCODED, page.content)
            self.assertIn(DIRECTOR_NAME_ENCODED, page.content)
            self.assertIn(CHARACTER_NAME_ENCODED, page.content)

        with self.subTest("виден в каталоге"):
            response = self.client.get(reverse("catalog:title_list"))
            self.assertIn(TITLE_NAME_ENCODED, response.content)

        with self.subTest("находится поиском"):
            for query in ("Полный", "Full Cycle"):
                found = self.client.get(
                    reverse("catalog:title_list"), {"q": query}
                )
                self.assertIn(TITLE_NAME_ENCODED, found.content)

    def test_unpublishing_removes_title_from_site(self):
        """Unpublishing via admin action must clear caches and remove
        the title from all public pages."""
        # ---- Arrange: publish first ----
        self.assertTrue(self._publish())
        self.title.refresh_from_db()
        self.assertEqual(self.title.status, STATUS_PUBLISHED)

        # Warm up caches by visiting pages
        self.client.get(self.title.get_absolute_url())
        self.client.get(reverse("catalog:title_list"))
        self.client.get(reverse("catalog:title_list"), {"q": "Полный"})

        # ---- Act: unpublish via admin action ----
        self.assertTrue(self._unpublish())
        self.title.refresh_from_db()
        self.assertEqual(self.title.status, STATUS_DRAFT)

        # ---- Assert: gone ----
        with self.subTest("страница фильма — 404"):
            response = self.client.get(self.title.get_absolute_url())
            self.assertEqual(response.status_code, 404)

        with self.subTest("нет в каталоге"):
            response = self.client.get(reverse("catalog:title_list"))
            self.assertNotIn(TITLE_NAME_ENCODED, response.content)

        with self.subTest("не находится поиском"):
            for query in ("Полный", "Full Cycle"):
                found = self.client.get(
                    reverse("catalog:title_list"), {"q": query}
                )
                self.assertNotIn(TITLE_NAME_ENCODED, found.content)

    def test_toggle_publish_clears_recommendation_cache(self):
        """Regression: toggling status must invalidate recommendations and
        similar-titles caches via invalidate_for_model."""
        self.assertTrue(self._publish())
        self.title.refresh_from_db()
        self.assertEqual(self.title.status, STATUS_PUBLISHED)

        # Visit pages that populate recommendation caches (home page)
        self.client.get(reverse("catalog:home"))

        # Unpublish — all caches should be invalidated
        self.assertTrue(self._unpublish())
        self.title.refresh_from_db()
        self.assertEqual(self.title.status, STATUS_DRAFT)

        # Visiting home should no longer mention the title
        home = self.client.get(reverse("catalog:home"))
        self.assertNotIn(TITLE_NAME_ENCODED, home.content)
