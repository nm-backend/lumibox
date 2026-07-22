import json

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from apps.core.test_factories import create_title, create_user
from apps.library.models import Favorite, WatchHistory
from apps.library.services import remember_view


class FavoriteModelTests(TestCase):
    def test_same_title_cannot_be_favorited_twice(self):
        """Проверки в коде мало: два одновременных запроса обошли бы её."""
        user = create_user()
        title = create_title()
        Favorite.objects.create(user=user, title=title)

        with self.assertRaises(IntegrityError):
            Favorite.objects.create(user=user, title=title)

    def test_different_users_favorite_same_title(self):
        title = create_title()
        Favorite.objects.create(user=create_user(), title=title)
        Favorite.objects.create(user=create_user(), title=title)

        self.assertEqual(Favorite.objects.filter(title=title).count(), 2)


class WatchHistoryModelTests(TestCase):
    def test_one_row_per_user_and_title(self):
        user = create_user()
        title = create_title()
        WatchHistory.objects.create(user=user, title=title)

        with self.assertRaises(IntegrityError):
            WatchHistory.objects.create(user=user, title=title)

    def test_repeat_view_updates_timestamp(self):
        user = create_user()
        title = create_title()

        remember_view(user, title)
        first = WatchHistory.objects.get(user=user, title=title).watched_at

        remember_view(user, title)
        second = WatchHistory.objects.get(user=user, title=title).watched_at

        self.assertGreater(second, first)


class ToggleFavoriteViewTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.title = create_title()
        self.url = reverse("library:toggle_favorite", args=[self.title.slug])

    def test_guest_redirected_to_login(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("users:login"), response.url)
        self.assertEqual(Favorite.objects.count(), 0)

    def test_get_does_not_change_anything(self):
        """
        GET не должен менять данные: иначе поисковый робот,
        пройдя по ссылке, вычистил бы всё избранное пользователя.
        """
        self.client.force_login(self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(Favorite.objects.count(), 0)

    def test_post_toggles_on_and_off(self):
        self.client.force_login(self.user)

        self.client.post(self.url)
        self.assertTrue(Favorite.objects.filter(user=self.user, title=self.title).exists())

        self.client.post(self.url)
        self.assertFalse(Favorite.objects.filter(user=self.user, title=self.title).exists())

    def test_ajax_request_gets_json(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, headers={"x-requested-with": "XMLHttpRequest"})

        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(json.loads(response.content), {"is_favorite": True})

    def test_plain_form_gets_redirect(self):
        """Без JavaScript форма должна работать обычным редиректом."""
        self.client.force_login(self.user)
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 302)

    def test_next_cannot_send_user_to_another_site(self):
        """
        next приходит из формы, то есть от клиента. Без проверки он уводил
        на любой домен — готовая ссылка для фишинга.
        """
        self.client.force_login(self.user)

        response = self.client.post(self.url, {"next": "https://evil.example.com/phish"})

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("evil.example.com", response["Location"])
        self.assertEqual(response["Location"], self.title.get_absolute_url())

    def test_next_within_site_still_works(self):
        """Проверка не должна ломать нормальный возврат на страницу каталога."""
        self.client.force_login(self.user)

        response = self.client.post(self.url, {"next": "/catalog/?type=movie"})

        self.assertEqual(response["Location"], "/catalog/?type=movie")

    def test_draft_cannot_be_favorited(self):
        from apps.catalog.models import Title

        draft = create_title(status=Title.Status.DRAFT)
        self.client.force_login(self.user)

        response = self.client.post(reverse("library:toggle_favorite", args=[draft.slug]))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Favorite.objects.count(), 0)


class LibraryPagesTests(TestCase):
    def setUp(self):
        self.user = create_user()

    def test_favorites_require_login(self):
        response = self.client.get(reverse("library:favorites"))
        self.assertEqual(response.status_code, 302)

    def test_history_requires_login(self):
        response = self.client.get(reverse("library:history"))
        self.assertEqual(response.status_code, 302)

    def test_user_sees_only_own_favorites(self):
        mine = create_title(name="Мой фильм")
        stranger_title = create_title(name="Чужой фильм")

        Favorite.objects.create(user=self.user, title=mine)
        Favorite.objects.create(user=create_user(), title=stranger_title)

        self.client.force_login(self.user)
        response = self.client.get(reverse("library:favorites"))

        self.assertContains(response, "Мой фильм")
        self.assertNotContains(response, "Чужой фильм")

    def test_unpublished_title_hidden_from_favorites(self):
        """
        Снятый с публикации фильм остаётся в избранном записью в базе, но
        показывать его нельзя: ссылка ведёт на 404, а постер выглядит битым.
        """
        from apps.catalog.models import Title

        live = create_title(name="Живой фильм")
        pulled = create_title(name="Снятый фильм")
        Favorite.objects.create(user=self.user, title=live)
        Favorite.objects.create(user=self.user, title=pulled)

        Title.objects.filter(pk=pulled.pk).update(status=Title.Status.DRAFT)

        self.client.force_login(self.user)
        response = self.client.get(reverse("library:favorites"))

        self.assertContains(response, "Живой фильм")
        self.assertNotContains(response, "Снятый фильм")

    def test_unpublished_title_hidden_from_history(self):
        from apps.catalog.models import Title

        live = create_title(name="Живой просмотр")
        pulled = create_title(name="Снятый просмотр")
        remember_view(self.user, live)
        remember_view(self.user, pulled)

        Title.objects.filter(pk=pulled.pk).update(status=Title.Status.DRAFT)

        self.client.force_login(self.user)
        response = self.client.get(reverse("library:history"))

        self.assertContains(response, "Живой просмотр")
        self.assertNotContains(response, "Снятый просмотр")

    def test_clear_history_removes_only_own_rows(self):
        stranger = create_user()
        remember_view(self.user, create_title())
        remember_view(stranger, create_title())

        self.client.force_login(self.user)
        self.client.post(reverse("library:clear_history"))

        self.assertEqual(WatchHistory.objects.filter(user=self.user).count(), 0)
        self.assertEqual(WatchHistory.objects.filter(user=stranger).count(), 1)
