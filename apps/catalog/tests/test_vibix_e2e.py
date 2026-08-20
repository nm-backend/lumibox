from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from apps.catalog.models import Title
from apps.catalog.video_service_api import (
    VideoServiceAuthenticationError,
    VideoServicePermissionError,
    fetch_video_links,
    get_vibix_api_token,
    login_vibix,
)
from apps.catalog.video_service_sync import sync_title


class VibixE2ETests(TestCase):
    @patch("apps.catalog.video_service_api.requests.post")
    def test_login_vibix_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "mock-token-12345",
            "token_type": "Bearer",
            "role": "publisher",
            "id": 1184,
        }
        mock_post.return_value = mock_resp

        data = login_vibix(email="test@example.com", password="password")
        self.assertEqual(data["access_token"], "mock-token-12345")
        self.assertEqual(data["role"], "publisher")

    @patch("apps.catalog.video_service_api.requests.post")
    def test_login_vibix_invalid_credentials(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"message": "Invalid credentials"}
        mock_post.return_value = mock_resp

        with self.assertRaises(VideoServiceAuthenticationError):
            login_vibix(email="test@example.com", password="wrong")

    @override_settings(VIBIX_API_TOKEN="", VIDEO_SERVICE_API_KEY="")
    @patch("apps.catalog.video_service_api.login_vibix")
    def test_get_vibix_api_token_auto_login(self, mock_login):
        mock_login.return_value = {"access_token": "auto-logged-in-token"}
        token = get_vibix_api_token(auto_login=True)
        self.assertEqual(token, "auto-logged-in-token")

    @patch("apps.catalog.video_service_api._get")
    def test_fetch_video_links_sanitizes_limit(self, mock_get):
        mock_get.return_value = {"success": True, "data": [], "meta": {}}
        fetch_video_links("test-token", page=1, limit=5)
        # Should sanitize limit=5 to 20
        args, kwargs = mock_get.call_args
        params = args[2]
        self.assertEqual(params["limit"], 20)

    @patch("apps.catalog.video_service_sync.fetch_video_by_kp")
    @patch("apps.catalog.video_service_sync.iter_video_links")
    def test_sync_title_fallback_on_403(self, mock_iter, mock_fetch_kp):
        mock_fetch_kp.side_effect = VideoServicePermissionError("403 Forbidden")
        mock_iter.return_value = [
            {
                "id": 999,
                "name": "Тестовый фильм",
                "name_rus": "Тестовый фильм",
                "name_eng": "Test Movie",
                "year": 2024,
                "kp_id": 123456,
                "imdb_id": "tt1234567",
                "embed_code": 'data-publisher-id="678503345" data-type="movie" data-id="55555"',
                "type": "movie",
                "description": "Описание фильма",
            }
        ]

        title = Title.objects.create(
            name="Тестовый фильм",
            slug="test-movie-2024",
            release_year=2024,
            kp_id="123456",
            imdb_id="tt1234567",
            status=Title.Status.PUBLISHED,
        )

        stats = sync_title(title)
        title.refresh_from_db()

        self.assertEqual(stats["matched"], 1)
        self.assertEqual(stats["player_filled"], 1)
        self.assertEqual(title.player_id, "55555")
        self.assertEqual(title.player_type, "movie")
        self.assertEqual(title.description, "Описание фильма")

    @patch("apps.catalog.video_service_sync.fetch_serial_by_kp")
    @patch("apps.catalog.video_service_sync.fetch_video_by_kp")
    def test_sync_series_creates_episodes(self, mock_fetch_video, mock_fetch_serial):
        mock_fetch_serial.return_value = {
            "id": 100,
            "name": "Тестовый сериал",
            "seasons": [
                {
                    "name": "Сезон 1",
                    "series": [{"name": "Эпизод 1"}, {"name": "Эпизод 2"}],
                }
            ],
        }
        mock_fetch_video.return_value = {
            "id": 100,
            "embed_code": 'data-publisher-id="678503345" data-type="serial" data-id="77777"',
            "type": "serial",
        }

        title = Title.objects.create(
            name="Тестовый сериал",
            slug="test-serial-2024",
            release_year=2024,
            kp_id="654321",
            type=Title.Type.SERIES,
            status=Title.Status.PUBLISHED,
        )

        stats = sync_title(title)
        title.refresh_from_db()

        self.assertEqual(stats["episodes_created"], 2)
        self.assertEqual(title.episodes.count(), 2)
        self.assertEqual(title.player_id, "77777")
        self.assertEqual(title.player_type, "series")
