"""
Тесты плеера: выбор озвучки, состав источников и разметка для поисковика.

Переключение серий и озвучек делает браузер, поэтому здесь проверяется
то, что отдаёт сервер: какие источники попали на страницу, какой из них
открывается первым и что видит поисковый робот.
"""

import json

from django.test import TestCase, override_settings

from apps.catalog.models import Participation, PlaybackSource, Title, VoiceOver
from apps.catalog.tests.test_episodes import create_episode, create_source
from apps.core.test_factories import (
    create_country,
    create_genre,
    create_participation,
    create_person,
    create_title,
)


class VoiceSelectorTests(TestCase):
    def setUp(self):
        self.title = create_title(name="Сериал с озвучками", type=Title.Type.SERIES)
        self.episode = create_episode(self.title, with_source=False)
        self.dubbed = VoiceOver.objects.create(name="Дубляж", slug="dubbed")
        self.original = VoiceOver.objects.create(name="Оригинал", slug="original")

    def test_selector_shown_when_several_voices(self):
        create_source(self.episode, voice=self.dubbed)
        create_source(self.episode, voice=self.original)

        response = self.client.get(self.title.get_absolute_url())

        self.assertContains(response, "player-voices")
        self.assertContains(response, "Дубляж")
        self.assertContains(response, "Оригинал")

    def test_selector_hidden_with_single_voice(self):
        """Одна кнопка без альтернативы — шум, а не выбор."""
        create_source(self.episode, voice=self.dubbed)

        response = self.client.get(self.title.get_absolute_url())

        self.assertNotContains(response, "player-voices")

    def test_voices_listed_once_across_episodes(self):
        second = create_episode(self.title, episode=2, with_source=False)
        create_source(self.episode, voice=self.dubbed)
        create_source(second, voice=self.dubbed)

        response = self.client.get(self.title.get_absolute_url())

        self.assertEqual(len(response.context["playback_voices"]), 1)


class PlaybackDataTests(TestCase):
    def test_data_lists_every_playable_source(self):
        title = create_title(type=Title.Type.SERIES)
        episode = create_episode(title, with_source=False)
        voice = VoiceOver.objects.create(name="Дубляж", slug="dubbed")
        create_source(episode, voice=voice)
        create_source(episode)

        response = self.client.get(title.get_absolute_url())

        data = response.context["playback_data"]
        self.assertEqual(len(data), 2)
        self.assertEqual({item["episode"] for item in data}, {episode.pk})

    def test_source_without_playable_address_skipped(self):
        """
        Кнопка озвучки, которая ничего не включает, хуже отсутствующей.

        Внешний плеер с недоверенного хоста даёт пустой src — такой источник
        в данные для скрипта не попадает.
        """
        title = create_title()
        PlaybackSource.objects.create(
            title=title,
            kind=PlaybackSource.Kind.EMBED,
            url="https://evil-youtube.com/embed/abc",
        )

        response = self.client.get(title.get_absolute_url())

        self.assertEqual(response.context["playback_data"], [])

    def test_data_rendered_as_json_script(self):
        title = create_title(type=Title.Type.SERIES)
        create_episode(title)

        response = self.client.get(title.get_absolute_url())

        self.assertContains(response, 'id="playback-data"')

    def test_no_player_section_without_sources(self):
        title = create_title(type=Title.Type.SERIES)
        create_episode(title, with_source=False)

        response = self.client.get(title.get_absolute_url())

        self.assertFalse(response.context["has_playback"])
        self.assertNotContains(response, "player-section")


class PrimarySourceTests(TestCase):
    def test_movie_uses_title_level_source(self):
        title = create_title(name="Фильм целиком")
        source = create_source(title=title)

        response = self.client.get(title.get_absolute_url())

        self.assertEqual(response.context["primary_source"], source)
        self.assertContains(response, source.src)

    def test_series_opens_on_first_episode(self):
        title = create_title(type=Title.Type.SERIES)
        first = create_episode(title, episode=1)
        create_episode(title, episode=2)

        response = self.client.get(title.get_absolute_url())

        self.assertEqual(response.context["primary_source"].episode_id, first.pk)


class TrailerRenderingTests(TestCase):
    def test_trailer_not_duplicated_across_page(self):
        """
        Трейлер рендерился трижды: вкладкой плеера, в описании и в модалке.

        Осталось два осмысленных места — вкладка и модальное окно.
        """
        title = create_title(
            name="Фильм с трейлером",
            trailer_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )
        create_source(title=title)

        html = self.client.get(title.get_absolute_url()).content.decode("utf-8")

        self.assertEqual(html.count("https://www.youtube.com/embed/dQw4w9WgXcQ"), 2)

    def test_untrusted_host_offers_outbound_link(self):
        title = create_title(trailer_url="https://evil-youtube.com/watch?v=x")
        create_source(title=title)

        response = self.client.get(title.get_absolute_url())

        self.assertContains(response, "Трейлер размещён на стороннем сервисе.")


@override_settings(VIDEO_SERVICE_PUBLISHER_ID="678503345")
class ExternalPlayerRenderingTests(TestCase):
    """Внешний плеер Vibix: тег <ins> с data-атрибутами и защита ключа.

    Разметку SDK забирает с официального CDN, а данные плеер получает
    из атрибутов тега — поэтому здесь проверяем именно их.
    """

    def test_series_renders_ins_with_season_and_episodes(self):
        title = create_title(
            name="Сериал с внешним плеером",
            type=Title.Type.SERIES,
            player_id="8285",
            player_type="serial",
        )
        create_episode(title, season=1, episode=1)
        create_episode(title, season=1, episode=2)

        response = self.client.get(title.get_absolute_url())

        self.assertContains(response, 'data-publisher-id="678503345"')
        self.assertContains(response, 'data-type="series"')
        self.assertContains(response, 'data-id="8285"')
        self.assertContains(response, 'data-season="1"')
        self.assertContains(response, 'data-episodes="1"')

    def test_movie_without_player_uses_kp_id(self):
        title = create_title(name="Фильм по kp", kp_id="4402886")

        response = self.client.get(title.get_absolute_url())

        self.assertContains(response, 'data-type="kp"')
        self.assertContains(response, 'data-id="4402886"')

    def test_external_player_is_primary_when_configured(self):
        """Внешний плеер — основной «Смотреть фильм»: вкладка открыта первой.

        Когда внешний плеер настроен, страница показывает ровно два плеера —
        фильм и трейлер. Запасные источники (YouTube, свои файлы) в разметку
        не попадают, чтобы зритель не путался в одинаковых вкладках.
        """
        title = create_title(
            name="Фильм с внешним плеером",
            video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            trailer_url="https://www.youtube.com/watch?v=9bZkp7q19f0",
            player_id="4427",
            player_type="movie",
        )
        create_source(title=title)

        response = self.client.get(title.get_absolute_url())

        # Вкладка внешнего плеера — «Смотреть фильм» и активна по умолчанию.
        self.assertContains(response, 'data-player-tab="external"')
        self.assertContains(response, "Смотреть фильм")
        self.assertContains(response, "Смотреть трейлер")
        # Запасные источники при настроенном внешнем плеере скрыты.
        self.assertNotContains(response, 'data-player-pane="youtube"')
        self.assertNotContains(response, 'data-player-pane="player1"')

    def test_youtube_pane_when_no_external_player(self):
        """Без внешнего плеера полная версия остаётся на YouTube."""
        title = create_title(
            name="Фильм на YouTube",
            video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )

        response = self.client.get(title.get_absolute_url())

        self.assertContains(response, 'data-player-pane="youtube"')
        self.assertNotContains(response, 'data-player-tab="external"')

    def test_no_external_player_without_ids(self):
        title = create_title(name="Ничего нет")

        response = self.client.get(title.get_absolute_url())

        self.assertNotContains(response, "data-publisher-id")
        self.assertNotContains(response, "vibix-player.js")

    def test_lazy_loader_only_with_external_player(self):
        with_player = create_title(name="С плеером", player_id="5", player_type="movie")
        response = self.client.get(with_player.get_absolute_url())
        self.assertContains(response, "vibix-player.js")
        self.assertContains(response, "data-vibix-load")
        # Mutable SDK не выполняется при простом открытии страницы.
        self.assertNotContains(
            response,
            '<script src="https://graphicslab.io/sdk/v2/rendex-sdk.min.js"',
            html=False,
        )

        without_player = create_title(name="Без плеера", player_id="", player_type="")
        self.assertNotContains(self.client.get(without_player.get_absolute_url()), "vibix-player.js")

    def test_api_token_never_reaches_html(self):
        title = create_title(name="Секретный плеер", player_id="5", player_type="movie")
        with self.settings(VIBIX_API_TOKEN="super-secret-token-abc"):
            response = self.client.get(title.get_absolute_url())

        self.assertNotContains(response, "super-secret-token-abc")

    def test_gate_has_content_wrapper_and_play_icon(self):
        title = create_title(name="С плеером", player_id="5", player_type="movie")
        response = self.client.get(title.get_absolute_url())
        self.assertContains(response, "vibix-player__gate-content")
        self.assertContains(response, "vibix-player__play-icon")

    def test_gate_shows_poster_preview_when_image_present(self):
        """Есть кадр/постер — до запуска он виден за кнопкой (превью плеера)."""
        title = create_title(name="С постером", player_id="5", player_type="movie")
        Title.objects.filter(pk=title.pk).update(backdrop="backdrops/test.jpg")

        response = self.client.get(title.get_absolute_url())

        self.assertContains(response, "vibix-player__preview")
        self.assertContains(response, "backdrops/test.jpg")

    def test_gate_without_image_has_no_preview(self):
        """Без картинок превью не рендерится — остаётся прежний тёмный фон."""
        title = create_title(name="Без картинок", player_id="5", player_type="movie")

        response = self.client.get(title.get_absolute_url())

        self.assertNotContains(response, "vibix-player__preview")

    def test_series_cta_says_watch_episodes(self):
        """Сериал с внешним плеером не должен называться «Смотреть фильм»."""
        title = create_title(
            name="Сериал с кнопкой",
            type=Title.Type.SERIES,
            player_id="8285",
            player_type="serial",
        )
        create_episode(title, season=1, episode=1)

        html = self.client.get(title.get_absolute_url()).content.decode("utf-8")

        self.assertIn("Смотреть серии", html)
        self.assertIn('href="#player"', html)
        self.assertIn('data-player-tab="external"', html)
        self.assertRegex(
            html,
            r'data-player-tab="external"[^>]*>\s*Смотреть серии',
        )

    def test_episode_buttons_carry_season_and_number(self):
        title = create_title(
            name="Сериал с кнопками", type=Title.Type.SERIES, player_id="7", player_type="serial"
        )
        create_episode(title, season=2, episode=3)

        response = self.client.get(title.get_absolute_url())

        self.assertContains(response, 'data-episode-season="2"')
        self.assertContains(response, 'data-episode-number="3"')


class StructuredDataTests(TestCase):
    """JSON-LD должен оставаться разбираемым и нести данные для сниппета."""

    def _payload(self, title):
        html = self.client.get(title.get_absolute_url()).content.decode("utf-8")
        start = html.find('<script type="application/ld+json">')
        body = html[html.find("{", start):html.find("</script>", start)]
        return json.loads(body)

    def test_movie_payload_has_crew_genres_and_countries(self):
        title = create_title(
            name="Фильм с разметкой",
            genres=[create_genre(name="Драма")],
            countries=[create_country(name="США")],
        )
        create_participation(
            title=title,
            person=create_person(name="Иван Режиссёров"),
            role=Participation.Role.DIRECTOR,
        )
        create_participation(
            title=title, person=create_person(name="Пётр Актёров"), role=Participation.Role.ACTOR
        )

        data = self._payload(title)

        self.assertEqual(data["@type"], "Movie")
        self.assertEqual(data["genre"], ["Драма"])
        self.assertEqual(data["countryOfOrigin"][0]["name"], "США")
        self.assertEqual(data["director"][0]["name"], "Иван Режиссёров")
        self.assertEqual(data["actor"][0]["name"], "Пётр Актёров")

    def test_series_payload_counts_seasons_and_episodes(self):
        title = create_title(name="Сериал с разметкой", type=Title.Type.SERIES)
        create_episode(title, season=1, episode=1)
        create_episode(title, season=1, episode=2)
        create_episode(title, season=2, episode=1)

        data = self._payload(title)

        self.assertEqual(data["@type"], "TVSeries")
        self.assertEqual(data["numberOfSeasons"], 2)
        self.assertEqual(data["numberOfEpisodes"], 3)

    def test_payload_survives_quotes_in_name(self):
        """Кавычки в названии не должны ломать разбор разметки."""
        title = create_title(name='Фильм "в кавычках"')

        self.assertEqual(self._payload(title)["name"], 'Фильм "в кавычках"')
