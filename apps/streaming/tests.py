"""
Тесты для streaming views и services.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Title
from apps.streaming.models import Episode, Season, VideoAsset
from apps.streaming.services import (
    get_next_episode,
    get_playback_source,
    get_watch_url,
    has_playback_access,
    save_watch_progress,
)

User = get_user_model()


class StreamingTestBase(TestCase):
    """Базовый класс с общими тестовыми данными."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="test@example.com",
            username="testuser",
            password="testpass123",
        )
        cls.title = Title.objects.create(
            name="Тестовый фильм",
            slug="test-film",
            release_year=2024,
            type=Title.Type.MOVIE,
            status=Title.Status.PUBLISHED,
            duration_minutes=120,
        )
        cls.asset = VideoAsset.objects.create(
            title=cls.title,
            provider=VideoAsset.Provider.CLOUDFLARE_STREAM,
            stream_type=VideoAsset.StreamType.HLS,
            asset_key="demo/test-stream",
            duration_seconds=7200,
            status=VideoAsset.Status.READY,
            access_level=VideoAsset.AccessLevel.FREE,
        )

        cls.series = Title.objects.create(
            name="Тестовый сериал",
            slug="test-series",
            release_year=2024,
            type=Title.Type.SERIES,
            status=Title.Status.PUBLISHED,
            duration_minutes=40,
        )
        cls.season = Season.objects.create(
            title=cls.series,
            number=1,
            name="Сезон 1",
        )
        cls.episode = Episode.objects.create(
            season=cls.season,
            number=1,
            name="Пилот",
            duration_seconds=2400,
        )
        cls.episode_asset = VideoAsset.objects.create(
            episode=cls.episode,
            provider=VideoAsset.Provider.CLOUDFLARE_STREAM,
            stream_type=VideoAsset.StreamType.HLS,
            asset_key="demo/test-stream",
            duration_seconds=2400,
            status=VideoAsset.Status.READY,
            access_level=VideoAsset.AccessLevel.FREE,
        )


class PlaybackAccessTests(StreamingTestBase):
    """Тесты проверки доступа к воспроизведению."""

    def test_free_asset_accessible(self):
        self.assertTrue(has_playback_access(self.user, self.asset))

    def test_draft_asset_not_accessible(self):
        self.asset.status = VideoAsset.Status.DRAFT
        self.asset.save()
        self.assertFalse(has_playback_access(self.user, self.asset))

    def test_expired_license_not_accessible(self):
        from datetime import timedelta

        from django.utils import timezone

        self.asset.license_ends_at = timezone.now() - timedelta(hours=1)
        self.asset.save()
        self.assertFalse(has_playback_access(self.user, self.asset))


class PlaybackSourceTests(StreamingTestBase):
    """Тесты получения источника воспроизведения."""

    def test_cloudflare_stream_source(self):
        source = get_playback_source(self.asset)
        self.assertIn("demo/test-stream", source.url)
        self.assertEqual(source.stream_type, "hls")

    def test_local_asset_without_file_raises(self):
        self.asset.provider = VideoAsset.Provider.LOCAL
        self.asset.media_file = ""
        self.asset.save()
        from apps.streaming.services import PlaybackUnavailable
        with self.assertRaises(PlaybackUnavailable):
            get_playback_source(self.asset)


class WatchUrlTests(StreamingTestBase):
    """Тесты получения URL для просмотра."""

    def test_movie_watch_url(self):
        url = get_watch_url(self.title)
        self.assertIsNotNone(url)
        self.assertIn(self.title.slug, url)

    def test_series_watch_url(self):
        url = get_watch_url(self.series)
        self.assertIsNotNone(url)
        self.assertIn(self.series.slug, url)

    def test_no_asset_returns_none(self):
        self.asset.delete()
        url = get_watch_url(self.title)
        self.assertIsNone(url)


class NextEpisodeTests(StreamingTestBase):
    """Тесты получения следующего эпизода."""

    def test_first_episode_returns_second(self):
        episode2 = Episode.objects.create(
            season=self.season, number=2, name="Серия 2"
        )
        VideoAsset.objects.create(
            episode=episode2,
            provider=VideoAsset.Provider.CLOUDFLARE_STREAM,
            stream_type=VideoAsset.StreamType.HLS,
            asset_key="demo/test-stream",
            duration_seconds=2400,
            status=VideoAsset.Status.READY,
        )
        next_ep = get_next_episode(self.episode)
        self.assertEqual(next_ep, episode2)

    def test_last_episode_returns_none(self):
        next_ep = get_next_episode(self.episode)
        self.assertIsNone(next_ep)


class WatchProgressTests(StreamingTestBase):
    """Тесты сохранения прогресса просмотра."""

    def test_save_progress(self):
        progress = save_watch_progress(
            user=self.user,
            asset=self.asset,
            position_seconds=300,
        )
        self.assertEqual(progress.position_seconds, 300)
        self.assertEqual(progress.duration_seconds, 7200)
        self.assertFalse(progress.is_completed)

    def test_near_completion_marks_completed(self):
        progress = save_watch_progress(
            user=self.user,
            asset=self.asset,
            position_seconds=7100,
        )
        self.assertTrue(progress.is_completed)
        self.assertEqual(progress.position_seconds, 7200)

    def test_position_normalized(self):
        progress = save_watch_progress(
            user=self.user,
            asset=self.asset,
            position_seconds=-10,
        )
        self.assertEqual(progress.position_seconds, 0)


class WatchViewTests(StreamingTestBase):
    """Тесты view для просмотра."""

    def test_watch_title_redirects_to_episode(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("streaming:watch_title", kwargs={"slug": self.series.slug})
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("season", response.url)

    def test_watch_movie_renders(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("streaming:watch_title", kwargs={"slug": self.title.slug})
        )
        self.assertEqual(response.status_code, 200)

    def test_watch_episode_renders(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "streaming:watch_episode",
                kwargs={
                    "slug": self.series.slug,
                    "season_number": 1,
                    "episode_number": 1,
                },
            )
        )
        self.assertEqual(response.status_code, 200)

    def test_watch_draft_returns_404(self):
        self.title.status = Title.Status.DRAFT
        self.title.save()
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("streaming:watch_title", kwargs={"slug": self.title.slug})
        )
        self.assertEqual(response.status_code, 404)
