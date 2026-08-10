"""Тесты прогресса просмотра: последняя серия, бейдж «Смотреть с S1E3»."""

import json

from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Title
from apps.catalog.templatetags.catalog_filters import lb_timecode
from apps.catalog.tests.test_episodes import create_episode
from apps.core.test_factories import create_title, create_user
from apps.library.models import WatchHistory
from apps.library.services import remember_episode_start, remember_view


def watch_url(slug):
    return reverse("api:v1:title-watch", args=[slug])


class RememberEpisodeStartTests(TestCase):
    def test_creates_history_row_with_episode(self):
        user = create_user()
        title = create_title(type=Title.Type.SERIES)
        episode = create_episode(title, season=1, episode=3)

        remember_episode_start(user, title, episode)

        history = WatchHistory.objects.get(user=user, title=title)
        self.assertEqual(history.episode, episode)

    def test_updates_episode_on_next_start(self):
        user = create_user()
        title = create_title(type=Title.Type.SERIES)
        first = create_episode(title, season=1, episode=1)
        second = create_episode(title, season=2, episode=1)

        remember_episode_start(user, title, first)
        remember_episode_start(user, title, second)

        history = WatchHistory.objects.get(user=user, title=title)
        self.assertEqual(history.episode, second)
        self.assertEqual(WatchHistory.objects.filter(user=user, title=title).count(), 1)

    def test_guest_ignored(self):
        from django.contrib.auth.models import AnonymousUser

        title = create_title(type=Title.Type.SERIES)
        episode = create_episode(title)

        remember_episode_start(AnonymousUser(), title, episode)
        self.assertEqual(WatchHistory.objects.count(), 0)

    def test_plain_page_view_keeps_episode(self):
        """Открытие страницы не стирает серию: прогресс и история — одна строка."""
        user = create_user()
        title = create_title(type=Title.Type.SERIES)
        episode = create_episode(title, season=1, episode=5)

        remember_episode_start(user, title, episode)
        remember_view(user, title)

        self.assertEqual(WatchHistory.objects.get(user=user, title=title).episode, episode)


class TitleWatchProgressViewTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.other_user = create_user()
        self.title = create_title(type=Title.Type.SERIES, name="Своя земля")
        self.episode = create_episode(self.title, season=1, episode=2)
        self.other_title = create_title(type=Title.Type.SERIES)
        self.other_episode = create_episode(self.other_title, season=1, episode=1)
        self.client.force_login(self.user)

    def test_guest_gets_403(self):
        self.client.logout()
        response = self.client.post(
            watch_url(self.title.slug),
            data=json.dumps({"episode": self.episode.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(WatchHistory.objects.count(), 0)

    def test_valid_start_saves_progress(self):
        response = self.client.post(
            watch_url(self.title.slug),
            data=json.dumps({"episode": self.episode.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            WatchHistory.objects.get(user=self.user, title=self.title).episode,
            self.episode,
        )

    def test_episode_of_another_title_rejected(self):
        response = self.client.post(
            watch_url(self.title.slug),
            data=json.dumps({"episode": self.other_episode.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(WatchHistory.objects.count(), 0)

    def test_missing_episode_number_rejected(self):
        response = self.client.post(
            watch_url(self.title.slug),
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_title_404(self):
        response = self.client.post(
            watch_url("no-such-title"),
            data=json.dumps({"episode": self.episode.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)


class TitleDetailResumeTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.title = create_title(type=Title.Type.SERIES, name="Разведка")
        self.first = create_episode(self.title, season=1, episode=1)
        self.resume = create_episode(self.title, season=1, episode=3, name="Прорыв")

    def test_guest_has_no_resume(self):
        response = self.client.get(self.title.get_absolute_url())
        self.assertIsNone(response.context["resume_episode"])
        # Гостю плеер открывает первую серию. Видео теперь приходит
        # из источника (PlaybackSource), а не из поля серии.
        self.assertContains(response, self.first.playback_sources.first().src)

    def test_user_with_progress_gets_resume_episode(self):
        remember_episode_start(self.user, self.title, self.resume)
        self.client.force_login(self.user)
        response = self.client.get(self.title.get_absolute_url())
        self.assertEqual(response.context["resume_episode"], self.resume)

    def test_player_opens_on_resume_episode(self):
        remember_episode_start(self.user, self.title, self.resume)
        self.client.force_login(self.user)
        response = self.client.get(self.title.get_absolute_url())

        self.assertContains(response, "Продолжить с S1E3")
        self.assertContains(response, self.resume.playback_sources.first().src)
        self.assertContains(response, "player-episode--active")
        self.assertContains(response, "Прорыв")

    def test_other_user_progress_not_leaked(self):
        remember_episode_start(create_user(), self.title, self.resume)
        self.client.force_login(self.user)
        response = self.client.get(self.title.get_absolute_url())
        self.assertIsNone(response.context["resume_episode"])
        self.assertNotContains(response, "Продолжить с S1E3")

    def test_page_view_without_episode_is_not_resume(self):
        remember_view(self.user, self.title)
        self.client.force_login(self.user)
        response = self.client.get(self.title.get_absolute_url())
        self.assertIsNone(response.context["resume_episode"])


class CatalogCardResumeTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.title = create_title(type=Title.Type.SERIES, name="Разведка")
        self.episode = create_episode(self.title, season=2, episode=4)
        self.catalog_url = reverse("catalog:title_list")

    def test_guest_card_has_no_resume_badge(self):
        response = self.client.get(self.catalog_url)
        html = response.content.decode("utf-8")
        self.assertNotIn("Смотреть с S2E4", html)
        self.assertNotIn("lb-shortstory__resume", html)

    def test_user_card_shows_resume_badge(self):
        remember_episode_start(self.user, self.title, self.episode)
        self.client.force_login(self.user)
        response = self.client.get(self.catalog_url)
        self.assertContains(response, "Смотреть с S2E4")

    def test_other_user_badge_not_shown(self):
        remember_episode_start(create_user(), self.title, self.episode)
        self.client.force_login(self.user)
        response = self.client.get(self.catalog_url)
        self.assertNotIn("Смотреть с S2E4", response.content.decode("utf-8"))

    def test_with_progress_uses_prefetch_not_n1(self):
        remember_episode_start(self.user, self.title, self.episode)
        self.client.force_login(self.user)

        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            self.client.get(self.catalog_url)
        progress_queries = [
            q
            for q in ctx.captured_queries
            if '"watchhistory"' in q["sql"] or "watchhistory" in q["sql"]
        ]
        self.assertEqual(len(progress_queries), 1)


class WithProgressPrefetchTests(TestCase):
    def test_progress_item_absent_for_guest(self):
        from django.contrib.auth.models import AnonymousUser

        titles = Title.objects.published().with_progress(AnonymousUser())
        title = titles.get(pk=create_title().pk)
        # to_attr не задаётся без prefetch: у гостя атрибута нет вовсе.
        self.assertFalse(hasattr(title, "progress_item"))

    def test_progress_item_contains_history_row(self):
        user = create_user()
        title = create_title(type=Title.Type.SERIES)
        episode = create_episode(title, season=1, episode=1)
        remember_episode_start(user, title, episode)

        fetched = Title.objects.published().with_progress(user).get(pk=title.pk)
        self.assertEqual(len(fetched.progress_item), 1)
        self.assertEqual(fetched.progress_item[0].episode, episode)


class HomeResumeBadgeTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.title = create_title(type=Title.Type.SERIES, name="Главная-сериал")
        self.episode = create_episode(self.title, season=3, episode=1)
        self.home_url = reverse("catalog:home")

    def test_guest_home_has_no_resume_badge(self):
        response = self.client.get(self.home_url)
        html = response.content.decode("utf-8")
        self.assertNotIn("Смотреть с S3E1", html)
        self.assertNotIn("lb-shortstory__resume", html)

    def test_user_home_shows_resume_badge(self):
        remember_episode_start(self.user, self.title, self.episode)
        self.client.force_login(self.user)
        response = self.client.get(self.home_url)
        self.assertContains(response, "Смотреть с S3E1")

    def test_other_user_badge_not_shown_on_home(self):
        remember_episode_start(create_user(), self.title, self.episode)
        self.client.force_login(self.user)
        response = self.client.get(self.home_url)
        self.assertNotIn("Смотреть с S3E1", response.content.decode("utf-8"))


class TimecodeFilterTests(TestCase):
    """Фильтр lb_timecode: секунды в подпись «Продолжить с 12:34»."""

    def test_formats(self):
        cases = [
            (0, "0:00"),
            (9, "0:09"),
            (754, "12:34"),
            (3600, "1:00:00"),
            (3723, "1:02:03"),
        ]
        for seconds, expected in cases:
            with self.subTest(seconds=seconds):
                self.assertEqual(lb_timecode(seconds), expected)

    def test_garbage_gives_empty_string(self):
        """Значение приходит из базы и из шаблона — падать оно не должно."""
        for value in [None, "", "abc", -1]:
            with self.subTest(value=value):
                self.assertEqual(lb_timecode(value), "")


class WatchPositionTests(TestCase):
    """
    Продолжение с секунды, а не с начала серии.

    До появления позиции история знала только, ЧТО зритель смотрел.
    «Продолжить» открывало серию с нуля, а для фильма без серий прогресс
    не сохранялся вовсе.
    """

    def setUp(self):
        self.user = create_user()
        self.series = create_title(type=Title.Type.SERIES, name="Сериал с позицией")
        self.episode = create_episode(self.series, season=1, episode=1)
        self.movie = create_title(type=Title.Type.MOVIE, name="Фильм с позицией")
        self.client.force_login(self.user)

    def _post(self, title, payload):
        return self.client.post(
            watch_url(title.slug), data=json.dumps(payload), content_type="application/json"
        )

    def test_position_saved_for_episode(self):
        response = self._post(self.series, {"episode": self.episode.pk, "position": 754})

        self.assertEqual(response.status_code, 200)
        history = WatchHistory.objects.get(user=self.user, title=self.series)
        self.assertEqual(history.position_seconds, 754)
        self.assertEqual(history.episode, self.episode)

    def test_duration_saved_when_player_reports_it(self):
        self._post(self.series, {"episode": self.episode.pk, "position": 10, "duration": 2400})

        history = WatchHistory.objects.get(user=self.user, title=self.series)
        self.assertEqual(history.duration_seconds, 2400)

    def test_movie_saves_progress_without_episode(self):
        """У фильма серий нет, и требовать их значило бы запретить ему прогресс."""
        response = self._post(self.movie, {"position": 120})

        self.assertEqual(response.status_code, 200)
        history = WatchHistory.objects.get(user=self.user, title=self.movie)
        self.assertEqual(history.position_seconds, 120)
        self.assertIsNone(history.episode)

    def test_series_still_requires_episode(self):
        response = self._post(self.series, {"position": 120})

        self.assertEqual(response.status_code, 400)

    def test_legacy_body_without_position_still_accepted(self):
        """Старое тело {"episode": id} означает «начал смотреть с начала»."""
        response = self._post(self.series, {"episode": self.episode.pk})

        self.assertEqual(response.status_code, 200)
        history = WatchHistory.objects.get(user=self.user, title=self.series)
        self.assertEqual(history.position_seconds, 0)

    def test_negative_position_rejected(self):
        response = self._post(self.series, {"episode": self.episode.pk, "position": -5})

        self.assertEqual(response.status_code, 400)

    def test_guest_cannot_save_position(self):
        self.client.logout()
        response = self._post(self.series, {"episode": self.episode.pk, "position": 30})

        self.assertEqual(response.status_code, 403)

    def test_detail_page_offers_resume_from_position(self):
        self._post(self.series, {"episode": self.episode.pk, "position": 754})

        response = self.client.get(self.series.get_absolute_url())

        self.assertEqual(response.context["resume_position"], 754)
        self.assertContains(response, 'data-resume-position="754"')
        # 754 секунды — это 12:34.
        self.assertContains(response, "12:34")

    def test_switching_episode_resets_position(self):
        """Новая серия начинается с нуля, а не с секунды предыдущей."""
        second = create_episode(self.series, season=1, episode=2)
        self._post(self.series, {"episode": self.episode.pk, "position": 754})

        self._post(self.series, {"episode": second.pk, "position": 0})

        history = WatchHistory.objects.get(user=self.user, title=self.series)
        self.assertEqual(history.episode, second)
        self.assertEqual(history.position_seconds, 0)

    def test_other_user_position_not_leaked(self):
        other = create_user()
        self.client.force_login(other)
        self._post(self.series, {"episode": self.episode.pk, "position": 900})

        self.client.force_login(self.user)
        response = self.client.get(self.series.get_absolute_url())

        self.assertEqual(response.context["resume_position"], 0)
