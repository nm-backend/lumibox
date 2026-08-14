"""Regression-тесты YouTube-плеера MVP.

Проверяется то, что отдаёт сервер: вкладка «Смотреть фильм» с iframe
только для валидной YouTube-ссылки, полная версия фильма не путается
с трейлером, серии сериала открывают свой ролик, а произвольный
iframe-адрес или чужой домен на страницу не попадают.
"""

from django.test import TestCase

from apps.catalog.models import Title
from apps.catalog.tests.test_episodes import create_episode
from apps.core.test_factories import create_title


class YoutubePlayerRenderingTests(TestCase):
    def test_movie_with_full_video_renders_embed(self):
        title = create_title(
            name="Фильм целиком на YouTube",
            video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )

        response = self.client.get(title.get_absolute_url())

        self.assertTrue(response.context["has_youtube"])
        self.assertEqual(
            response.context["youtube_video_url"],
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
        )
        self.assertContains(response, 'data-player-pane="youtube"')
        self.assertContains(response, "https://www.youtube.com/embed/dQw4w9WgXcQ")

    def test_movie_without_video_has_no_youtube_pane(self):
        title = create_title(name="Без видео")

        response = self.client.get(title.get_absolute_url())

        self.assertFalse(response.context["has_youtube"])
        self.assertNotContains(response, 'data-player-pane="youtube"')

    def test_foreign_domain_never_renders_iframe(self):
        """Vimeo-ссылка не должна превратиться в iframe ни в коем случае."""
        title = create_title(
            name="Чужой хостинг",
            video_url="https://vimeo.com/123456789",
        )

        response = self.client.get(title.get_absolute_url())

        self.assertFalse(response.context["has_youtube"])
        self.assertNotContains(response, "player.vimeo.com")
        self.assertNotContains(response, 'data-player-pane="youtube"')

    def test_malformed_url_never_renders_iframe(self):
        title = create_title(name="Битая ссылка", video_url="not a url")

        response = self.client.get(title.get_absolute_url())

        self.assertFalse(response.context["has_youtube"])
        self.assertNotContains(response, 'data-player-pane="youtube"')

    def test_trailer_and_full_video_are_separate(self):
        """Трейлер и полная версия — разные ролики, не должны путаться."""
        title = create_title(
            name="Трейлер и фильм",
            trailer_url="https://youtu.be/TRAILERID00",
            video_url="https://www.youtube.com/watch?v=FULLMOVIE00",
        )

        response = self.client.get(title.get_absolute_url())
        html = response.content.decode("utf-8")

        # Оба ролика на странице, каждый со своим ID.
        self.assertIn("https://www.youtube.com/embed/TRAILERID00", html)
        self.assertIn("https://www.youtube.com/embed/FULLMOVIE00", html)


class YoutubeSeriesTests(TestCase):
    def test_series_with_episode_videos_gets_youtube_pane(self):
        title = create_title(type=Title.Type.SERIES, name="Сериал на YouTube")
        create_episode(
            title,
            season=1,
            episode=1,
            with_source=False,
            video_url="https://youtu.be/EPISODEONE1",
        )
        create_episode(
            title,
            season=1,
            episode=2,
            with_source=False,
            video_url="https://www.youtube.com/watch?v=EPISODETWO2",
        )

        response = self.client.get(title.get_absolute_url())

        self.assertTrue(response.context["has_youtube"])
        self.assertIsNone(response.context["youtube_video_url"])
        self.assertContains(response, 'data-player-pane="youtube"')
        # У каждой кнопки серии свой адрес ролика.
        self.assertContains(response, 'data-episode-youtube="https://www.youtube.com/embed/EPISODEONE1"')
        self.assertContains(response, 'data-episode-youtube="https://www.youtube.com/embed/EPISODETWO2"')

    def test_episode_without_video_has_no_youtube_attribute(self):
        title = create_title(type=Title.Type.SERIES, name="Сериал без видео")
        create_episode(title, season=1, episode=1, with_source=False)
        create_episode(
            title,
            season=1,
            episode=2,
            with_source=False,
            video_url="https://youtu.be/ONLYSECOND1",
        )

        response = self.client.get(title.get_absolute_url())

        # Первая серия без ролика — атрибута нет; вторая — с роликом.
        self.assertNotContains(response, 'data-episode-youtube=""')
        self.assertContains(response, 'data-episode-youtube="https://www.youtube.com/embed/ONLYSECOND1"')


class YoutubeSecurityTests(TestCase):
    def test_xss_payload_never_renders(self):
        title = create_title(
            name="XSS-попытка",
            video_url='https://www.youtube.com/watch?v="><script>alert(1)</script>',
        )

        response = self.client.get(title.get_absolute_url())

        self.assertFalse(response.context["has_youtube"])
        self.assertNotContains(response, "alert(1)")

    def test_arbitrary_iframe_html_rejected(self):
        title = create_title(
            name="HTML вместо ссылки",
            video_url='<iframe src="https://evil.example"></iframe>',
        )

        response = self.client.get(title.get_absolute_url())

        self.assertFalse(response.context["has_youtube"])
        self.assertNotContains(response, "evil.example")

    def test_javascript_url_rejected(self):
        title = create_title(
            name="JavaScript-схема",
            video_url="javascript:alert(document.cookie)",
        )

        response = self.client.get(title.get_absolute_url())

        self.assertFalse(response.context["has_youtube"])
        self.assertNotContains(response, "alert(")
