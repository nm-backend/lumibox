from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Title
from apps.core.test_factories import create_title


class TitleAdminTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            email="editor@example.com",
            username="editor",
            password="secure-test-password",
        )
        self.client.force_login(self.user)

    def test_add_form_opens_for_staff(self):
        """Нередактируемое поле не должно ломать создание записи в админке."""
        response = self.client.get(reverse("admin:catalog_title_add"))

        self.assertEqual(response.status_code, 200)

    def test_add_form_has_video_section(self):
        """Секция «Видео» с полями трейлера и полной версии — на месте."""
        response = self.client.get(reverse("admin:catalog_title_add"))

        self.assertContains(response, "Видео")
        self.assertContains(response, 'name="video_url"')
        self.assertContains(response, 'name="trailer_url"')

    def test_list_search_finds_by_kp_id(self):
        """Поиск по KP ID находит фильм — нужно для быстрого наполнения."""
        create_title(name="Интерстеллар", kp_id="2643")

        response = self.client.get(reverse("admin:catalog_title_changelist"), {"q": "2643"})

        self.assertContains(response, "Интерстеллар")

    def test_list_search_finds_by_imdb_id(self):
        create_title(name="Начало", imdb_id="tt1375666")

        response = self.client.get(reverse("admin:catalog_title_changelist"), {"q": "tt1375666"})

        self.assertContains(response, "Начало")

    def test_bulk_publish_action(self):
        """Bulk-публикация меняет статус выбранных записей разом."""
        draft = create_title(name="Черновик", status=Title.Status.DRAFT)
        other = create_title(name="Ещё черновик", status=Title.Status.DRAFT)
        changelist = reverse("admin:catalog_title_changelist")

        response = self.client.post(
            changelist,
            {
                "action": "publish",
                "_selected_action": [str(draft.pk), str(other.pk)],
            },
        )

        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(draft.status, Title.Status.PUBLISHED)
        self.assertEqual(other.status, Title.Status.PUBLISHED)

    def test_bulk_unpublish_action(self):
        published = create_title(name="Опубликованное", status=Title.Status.PUBLISHED)
        changelist = reverse("admin:catalog_title_changelist")

        response = self.client.post(
            changelist,
            {
                "action": "unpublish",
                "_selected_action": [str(published.pk)],
            },
        )

        self.assertEqual(response.status_code, 302)
        published.refresh_from_db()
        self.assertEqual(published.status, Title.Status.DRAFT)

    def _empty_inline_management(self):
        """Пустые management-данные для инлайнов формы записи."""
        data = {}
        for prefix in ("participations", "frames", "award_entries", "episodes", "playback_sources"):
            data.update(
                {
                    f"{prefix}-TOTAL_FORMS": "0",
                    f"{prefix}-INITIAL_FORMS": "0",
                    f"{prefix}-MIN_NUM_FORMS": "0",
                    f"{prefix}-MAX_NUM_FORMS": "1000",
                }
            )
        return data

    def _base_title_fields(self, **kwargs):
        fields = {
            "type": Title.Type.MOVIE,
            "name": "Тестовый фильм",
            "slug": "testovyy-film",
            "release_year": 2020,
            "status": Title.Status.PUBLISHED,
        }
        fields.update(kwargs)
        return fields

    def test_video_url_field_rejects_foreign_domain(self):
        """Чужой домен в video_url не должен пройти сохранение формы."""
        data = self._base_title_fields(
            name="Нельзя так",
            slug="nelzya-tak",
            video_url="https://vimeo.com/123456789",
        )
        data.update(self._empty_inline_management())
        data.update({"genres": [], "countries": [], "studios": [], "related_titles": []})

        response = self.client.post(reverse("admin:catalog_title_add"), data)

        self.assertEqual(response.status_code, 200)  # форма вернулась с ошибкой
        self.assertContains(response, "корректную ссылку на видео YouTube")

    def test_video_url_field_accepts_youtube(self):
        data = self._base_title_fields(
            name="Можно так",
            slug="mozhno-tak",
            video_url="https://youtu.be/dQw4w9WgXcQ",
        )
        data.update(self._empty_inline_management())
        data.update({"genres": [], "countries": [], "studios": [], "related_titles": []})

        response = self.client.post(reverse("admin:catalog_title_add"), data)

        self.assertEqual(response.status_code, 302)  # запись создана


class EpisodeAdminTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            email="editor@example.com",
            username="editor",
            password="secure-test-password",
        )
        self.client.force_login(self.user)

    def test_episode_search_finds_by_series_name(self):
        title = create_title(name="Сериал-миллионник", type=Title.Type.SERIES)
        from apps.catalog.models import Episode

        Episode.objects.create(title=title, season_number=1, episode_number=3, name="Пилот")

        response = self.client.get(reverse("admin:catalog_episode_changelist"), {"q": "миллионник"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Пилот")
