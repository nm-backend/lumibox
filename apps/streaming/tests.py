"""
Тесты стриминга: сервисы доступа, эндпоинты плеера и просмотр.

Покрывает:
- has_playback_access — проверка прав на воспроизведение
- save_watch_progress — сохранение позиции просмотра
- get_continue_watching — продолжение просмотра
- get_next_episode — навигация по сериям
- get_watch_url — точка входа в просмотр
- PlaybackViews — эндпоинты продолжателя, прогресса и конфигурации
- WatchTitleView — страница просмотра фильма
"""

from django.contrib.auth.models import AnonymousUser
from django.test import Client, TestCase
from django.urls import reverse

from apps.core.test_factories import create_title, create_user
from apps.streaming.models import VideoAsset, WatchProgress

# =============================================================================
# has_playback_access
# =============================================================================

class HasPlaybackAccessTests(TestCase):
    """Проверки доступа к воспроизведению."""

    def test_guest_cannot_access_premium(self):
        """Неавторизованный пользователь не имеет доступа к премиум-контенту."""
        from apps.streaming.services import has_playback_access

        user = AnonymousUser()
        title = create_title(status="published")
        asset = VideoAsset(
            title=title,
            status=VideoAsset.Status.READY,
            access_level=VideoAsset.AccessLevel.PREMIUM,
            duration_seconds=3600,
        )

        self.assertFalse(has_playback_access(user, asset))

    def test_free_accessible_by_anyone(self):
        """Бесплатный контент доступен любому авторизованному."""
        from apps.streaming.services import has_playback_access

        user = create_user()
        title = create_title(status="published")
        asset = VideoAsset.objects.create(
            title=title,
            status=VideoAsset.Status.READY,
            access_level=VideoAsset.AccessLevel.FREE,
            duration_seconds=3600,
        )

        self.assertTrue(has_playback_access(user, asset))

    def test_staff_can_access_premium(self):
        """Редактор может просматривать премиум-контент для предпросмотра."""
        from apps.streaming.services import has_playback_access

        user = create_user()
        user.is_staff = True
        user.save()

        title = create_title(status="published")
        asset = VideoAsset.objects.create(
            title=title,
            status=VideoAsset.Status.READY,
            access_level=VideoAsset.AccessLevel.PREMIUM,
            duration_seconds=3600,
        )

        self.assertTrue(has_playback_access(user, asset))

    def test_not_available_asset_denied(self):
        """Недоступный (черновик) ресурс не воспроизводится."""
        from apps.streaming.services import has_playback_access

        user = create_user()
        title = create_title(status="published")
        asset = VideoAsset(
            title=title,
            status=VideoAsset.Status.DRAFT,
            access_level=VideoAsset.AccessLevel.FREE,
            duration_seconds=3600,
        )

        self.assertFalse(has_playback_access(user, asset))


# =============================================================================
# save_watch_progress
# =============================================================================

class SaveWatchProgressTests(TestCase):
    """Сохранение позиции просмотра."""

    def setUp(self):
        self.user = create_user()
        self.title = create_title(status="published")

    def test_saves_normal_position(self):
        """Обычная позиция сохраняется корректно."""
        from apps.streaming.services import save_watch_progress

        asset = VideoAsset.objects.create(
            title=self.title,
            status=VideoAsset.Status.READY,
            access_level=VideoAsset.AccessLevel.FREE,
            duration_seconds=3600,
        )

        progress = save_watch_progress(
            user=self.user,
            asset=asset,
            position_seconds=300,
        )

        self.assertEqual(progress.position_seconds, 300)
        self.assertFalse(progress.is_completed)

    def test_normalizes_negative_position(self):
        """Отрицательная позиция нормализуется к 0."""
        from apps.streaming.services import save_watch_progress

        asset = VideoAsset.objects.create(
            title=self.title,
            status=VideoAsset.Status.READY,
            access_level=VideoAsset.AccessLevel.FREE,
            duration_seconds=3600,
        )

        progress = save_watch_progress(
            user=self.user,
            asset=asset,
            position_seconds=-100,
        )

        self.assertEqual(progress.position_seconds, 0)

    def test_normalizes_excessive_position(self):
        """Позиция больше длительности нормализуется с завершением."""
        from apps.streaming.services import save_watch_progress

        asset = VideoAsset.objects.create(
            title=self.title,
            status=VideoAsset.Status.READY,
            access_level=VideoAsset.AccessLevel.FREE,
            duration_seconds=3600,
        )

        progress = save_watch_progress(
            user=self.user,
            asset=asset,
            position_seconds=99999,
        )

        self.assertEqual(progress.position_seconds, 3600)
        self.assertTrue(progress.is_completed)

    def test_explicit_completed(self):
        """Явное завершение сохраняется корректно."""
        from apps.streaming.services import save_watch_progress

        asset = VideoAsset.objects.create(
            title=self.title,
            status=VideoAsset.Status.READY,
            access_level=VideoAsset.AccessLevel.FREE,
            duration_seconds=3600,
        )

        progress = save_watch_progress(
            user=self.user,
            asset=asset,
            position_seconds=3600,
            is_completed=True,
        )

        self.assertTrue(progress.is_completed)
        self.assertEqual(progress.position_seconds, 3600)


# =============================================================================
# get_continue_watching
# =============================================================================

class GetContinueWatchingTests(TestCase):
    """Продолжение просмотра."""

    def setUp(self):
        self.user = create_user()
        self.title = create_title(status="published")

    def test_guest_gets_empty(self):
        """Гость не имеет истории просмотров."""
        from apps.streaming.services import get_continue_watching

        user = AnonymousUser()
        result = get_continue_watching(user)
        self.assertEqual(len(result), 0)

    def test_authenticated_user_no_progress(self):
        """Авторизованный пользователь без просмотров получает пустой список."""
        from apps.streaming.services import get_continue_watching

        result = get_continue_watching(self.user)
        self.assertEqual(len(result), 0)

    def test_authenticated_user_with_progress(self):
        """Авторизованный пользователь с прогрессом получает его в списке."""
        from apps.streaming.services import get_continue_watching

        asset = VideoAsset.objects.create(
            title=self.title,
            access_level=VideoAsset.AccessLevel.FREE,
            status=VideoAsset.Status.READY,
            duration_seconds=3600,
        )

        WatchProgress.objects.create(
            user=self.user,
            video_asset=asset,
            position_seconds=120,
            duration_seconds=3600,
            is_completed=False,
        )

        result = get_continue_watching(self.user)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].position_seconds, 120)

    def test_completed_progress_excluded(self):
        """Завершённые просмотры не показываются."""
        from apps.streaming.services import get_continue_watching

        asset = VideoAsset.objects.create(
            title=self.title,
            access_level=VideoAsset.AccessLevel.FREE,
            status=VideoAsset.Status.READY,
            duration_seconds=3600,
        )

        WatchProgress.objects.create(
            user=self.user,
            video_asset=asset,
            position_seconds=3600,
            duration_seconds=3600,
            is_completed=True,
        )

        result = get_continue_watching(self.user)
        self.assertEqual(len(result), 0)

    def test_short_progress_excluded(self):
        """Просмотр короче 30 секунд не считается."""
        from apps.streaming.services import get_continue_watching

        asset = VideoAsset.objects.create(
            title=self.title,
            access_level=VideoAsset.AccessLevel.FREE,
            status=VideoAsset.Status.READY,
            duration_seconds=3600,
        )

        WatchProgress.objects.create(
            user=self.user,
            video_asset=asset,
            position_seconds=15,
            duration_seconds=3600,
            is_completed=False,
        )

        result = get_continue_watching(self.user)
        self.assertEqual(len(result), 0)


# =============================================================================
# get_next_episode
# =============================================================================

class GetNextEpisodeTests(TestCase):
    """Поиск следующей серии."""

    def test_none_episode_returns_none(self):
        """None вместо эпизода возвращает None."""
        from apps.streaming.services import get_next_episode

        self.assertIsNone(get_next_episode(None))


# =============================================================================
# get_watch_url
# =============================================================================

class GetWatchUrlTests(TestCase):
    """Точка входа в просмотр."""

    def test_movie_without_asset_returns_none(self):
        """Фильм без видеоресурса возвращает None."""
        from apps.streaming.services import get_watch_url

        title = create_title(status="published", type="movie")
        result = get_watch_url(title)
        self.assertIsNone(result)

    def test_movie_with_asset_returns_url(self):
        """Фильм с видеоресурсом возвращает URL просмотра."""
        from apps.streaming.services import get_watch_url

        title = create_title(status="published", type="movie")
        VideoAsset.objects.create(
            title=title,
            status=VideoAsset.Status.READY,
            access_level=VideoAsset.AccessLevel.FREE,
            duration_seconds=3600,
        )

        result = get_watch_url(title)
        self.assertIsNotNone(result)
        self.assertIn(title.slug, result)


# =============================================================================
# Playback API Views (auth check)
# =============================================================================

class PlaybackViewsTests(TestCase):
    """API эндпоинты плеера — проверка авторизации."""

    def setUp(self):
        self.client = Client()

    def test_continue_watching_requires_auth(self):
        """Список продолжения просмотра возвращает 403 без авторизации."""
        url = reverse("streaming:continue_watching_api")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_progress_requires_auth(self):
        """Сохранение прогресса возвращает 403 без авторизации."""
        url = reverse("streaming:progress_api")
        response = self.client.post(
            url,
            {"asset_id": "00000000-0000-0000-0000-000000000000", "position_seconds": 0},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_configuration_api_requires_auth(self):
        """Конфигурация плеера требует авторизации."""
        url = reverse("streaming:configuration_api", kwargs={"asset_id": "00000000-0000-0000-0000-000000000000"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)


# =============================================================================
# ContinueWatchingApiView
# =============================================================================

class ContinueWatchingApiViewTests(TestCase):
    """API продолжения просмотра."""

    def setUp(self):
        self.client = Client()
        self.user = create_user()
        self.client.force_login(self.user)

    def test_empty_for_user_without_progress(self):
        """Пользователь без прогресса получает пустой массив."""
        url = reverse("streaming:continue_watching_api")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_returns_progress_items(self):
        """Пользователь с прогрессом получает свои записи."""
        title = create_title(status="published")
        asset = VideoAsset.objects.create(
            title=title,
            access_level=VideoAsset.AccessLevel.FREE,
            status=VideoAsset.Status.READY,
            duration_seconds=3600,
        )

        WatchProgress.objects.create(
            user=self.user,
            video_asset=asset,
            position_seconds=300,
            duration_seconds=3600,
            is_completed=False,
        )

        url = reverse("streaming:continue_watching_api")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["position_seconds"], 300)

    def test_completed_items_excluded(self):
        """Завершённые элементы не возвращаются."""
        title = create_title(status="published")
        asset = VideoAsset.objects.create(
            title=title,
            access_level=VideoAsset.AccessLevel.FREE,
            status=VideoAsset.Status.READY,
            duration_seconds=3600,
        )

        WatchProgress.objects.create(
            user=self.user,
            video_asset=asset,
            position_seconds=3600,
            duration_seconds=3600,
            is_completed=True,
        )

        url = reverse("streaming:continue_watching_api")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])


# =============================================================================
# WatchTitleView (page rendering)
# =============================================================================

class WatchTitleViewTests(TestCase):
    """Страница просмотра фильма."""

    def setUp(self):
        self.client = Client()
        self.user = create_user()

    def test_unpublished_title_returns_404(self):
        """Неопубликованный фильм возвращает 404."""
        self.client.force_login(self.user)
        title = create_title(status="draft", type="movie")

        url = reverse("streaming:watch_title", kwargs={"slug": title.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_published_movie_without_asset_returns_404(self):
        """Опубликованный фильм без видеоресурса возвращает 404."""
        self.client.force_login(self.user)
        title = create_title(status="published", type="movie")

        url = reverse("streaming:watch_title", kwargs={"slug": title.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


# =============================================================================
# PlaybackConfigurationApiView
# =============================================================================

class PlaybackConfigurationApiViewTests(TestCase):
    """API конфигурации плеера."""

    def setUp(self):
        self.client = Client()
        self.user = create_user()
        self.client.force_login(self.user)

    def test_nonexistent_asset_returns_404(self):
        """Несуществующий ресурс возвращает 404."""
        url = reverse(
            "streaming:configuration_api",
            kwargs={"asset_id": "00000000-0000-0000-0000-000000000000"},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
