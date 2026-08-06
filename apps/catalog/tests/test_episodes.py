"""Тесты серий (Episode) и новых полей качества и внешних рейтингов."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Episode, Title
from apps.core.test_factories import create_title


def episode_file(name="episode.mp4"):
    return SimpleUploadedFile(name, b"fake-video-bytes", content_type="video/mp4")


def create_episode(title, season=1, episode=1, **kwargs):
    kwargs.setdefault("season_number", season)
    kwargs.setdefault("episode_number", episode)
    kwargs.setdefault("file", episode_file())
    return Episode.objects.create(title=title, **kwargs)


class EpisodeModelTests(TestCase):
    def test_ordering_by_season_then_episode(self):
        title = create_title()
        create_episode(title, season=2, episode=2)
        create_episode(title, season=1, episode=2)
        create_episode(title, season=1, episode=1)

        self.assertEqual(
            list(title.episodes.values_list("season_number", "episode_number")),
            [(1, 1), (1, 2), (2, 2)],
        )

    def test_duplicate_season_episode_rejected(self):
        title = create_title()
        create_episode(title, season=1, episode=1)
        with self.assertRaises(IntegrityError):
            create_episode(title, season=1, episode=1)

    def test_same_episode_number_in_different_seasons_allowed(self):
        title = create_title()
        create_episode(title, season=1, episode=1)
        create_episode(title, season=2, episode=1)
        self.assertEqual(Episode.objects.count(), 2)

    def test_episodes_of_different_titles_do_not_collide(self):
        create_episode(create_title(), season=1, episode=1)
        create_episode(create_title(), season=1, episode=1)
        self.assertEqual(Episode.objects.count(), 2)

    def test_str_shows_season_episode_and_title(self):
        episode = create_episode(create_title(name="Северное сияние"), episode=3)
        self.assertIn("S1E3", str(episode))
        self.assertIn("Северное сияние", str(episode))


class TitleDetailEpisodeTests(TestCase):
    def test_player_section_rendered_for_title_with_episodes(self):
        title = create_title(type=Title.Type.SERIES, name="Разведка")
        create_episode(title, season=1, episode=1, name="Пилот")
        create_episode(title, season=1, episode=2)
        create_episode(title, season=2, episode=1)

        response = self.client.get(title.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "player-section")
        self.assertContains(response, "Смотреть онлайн")
        self.assertContains(response, "Пилот")
        self.assertContains(response, "Сезон 2")
        self.assertContains(response, "2 сезона")
        self.assertContains(response, "3 серии")

    def test_player_section_hidden_without_episodes(self):
        title = create_title()
        response = self.client.get(title.get_absolute_url())
        self.assertNotContains(response, "player-section")
        self.assertNotContains(response, "Смотреть онлайн")

    def test_episode_stats_in_context(self):
        title = create_title(type=Title.Type.SERIES)
        create_episode(title, season=1, episode=1)
        create_episode(title, season=1, episode=2)
        create_episode(title, season=2, episode=1)

        response = self.client.get(title.get_absolute_url())

        self.assertEqual(response.context["episode_stats"], {"seasons": 2, "count": 3})
        self.assertEqual(len(response.context["episodes"]), 3)

    def test_episode_stats_none_without_episodes(self):
        response = self.client.get(create_title().get_absolute_url())
        self.assertIsNone(response.context["episode_stats"])

    def test_draft_with_episodes_still_hidden(self):
        title = create_title(status=Title.Status.DRAFT)
        create_episode(title)
        response = self.client.get(title.get_absolute_url())
        self.assertEqual(response.status_code, 404)


class TitleExtraMetaTests(TestCase):
    def test_quality_and_external_ratings_shown_on_detail(self):
        title = create_title(
            quality=Title.Quality.WEB_DL,
            imdb_rating="8.2",
            kp_rating="7.8",
        )
        response = self.client.get(title.get_absolute_url())

        self.assertContains(response, "WEB-DL")
        self.assertContains(response, "IMDb 8.2")
        self.assertContains(response, "Кинопоиск 7.8")

    def test_external_ratings_hidden_when_empty(self):
        title = create_title()
        response = self.client.get(title.get_absolute_url())
        self.assertNotContains(response, "IMDb")
        self.assertNotContains(response, "Кинопоиск")

    def test_quality_and_ratings_shown_on_catalog_card(self):
        create_title(
            name="Особенный фильм",
            quality=Title.Quality.BDRIP,
            imdb_rating="9.1",
            kp_rating="8.9",
        )
        response = self.client.get(reverse("catalog:title_list"))
        html = response.content.decode("utf-8")
        marker = html.find("Особенный фильм")
        self.assertNotEqual(marker, -1)
        self.assertIn("BDRip", html)
        self.assertIn("КП 8.9", html)
        self.assertIn("IMDb 9.1", html)

    def test_card_without_extra_meta_stays_clean(self):
        create_title(name="Обычный фильм")
        response = self.client.get(reverse("catalog:title_list"))
        html = response.content.decode("utf-8")
        self.assertNotIn("IMDb", html)
        self.assertNotIn("КП ", html)
