"""
Тесты синхронизации каталога с API видеосервиса (sync_video_service).

Внешний API не трогаем: HTTP-клиент замокан на уровне requests,
а сама синхронизация — на уровне генератора iter_video_links.
"""

from datetime import datetime
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.catalog.models import (
    Country,
    Episode,
    Genre,
    Title,
    VideoServiceSyncState,
    VoiceOver,
)
from apps.catalog.video_service_api import (
    MAX_RETRIES,
    VIDEO_SERVICE_API_BASE,
    VIDEO_SERVICE_SERIALS_API_BASE,
    VideoServiceAPIError,
    VideoServiceNotFoundError,
    fetch_categories,
    fetch_countries,
    fetch_genres,
    fetch_serial_by_imdb,
    fetch_serial_by_kp,
    fetch_tags,
    fetch_video_by_imdb,
    fetch_video_by_kp,
    fetch_video_kpids,
    fetch_video_links,
    fetch_voiceovers,
    iter_video_links,
)
from apps.catalog.video_service_sync import (
    _filter_years,
    match_item,
    normalize_name,
    sync_series_episodes,
    sync_title,
    sync_video_service_ids,
)
from apps.catalog.video_service_voiceover_sync import import_voiceovers_from_service, sync_voiceover_ids
from apps.core.test_factories import create_title


class NormalizeNameTests(TestCase):
    def test_lowercase_and_punctuation(self):
        self.assertEqual(normalize_name("ЁЛКА!"), "ёлка")

    def test_collapses_spaces(self):
        self.assertEqual(normalize_name("  Начало:  Часть 2  "), "начало часть 2")

    def test_quotes_are_separators(self):
        self.assertEqual(normalize_name("«Ёлки-2»"), "ёлки 2")

    def test_empty_values(self):
        self.assertEqual(normalize_name(""), "")
        self.assertEqual(normalize_name(None), "")


class MatchItemTests(TestCase):
    def test_matches_by_russian_name(self):
        index = {"начало": [create_title(name="Начало", release_year=2010)]}
        item = {"name": "Начало", "year": "2010", "kp_id": 1, "imdb_id": "tt1"}
        self.assertIsNotNone(match_item(index, item))

    def test_matches_by_original_name(self):
        title = create_title(name="Начало", original_name="Inception", release_year=2010)
        index = {"inception": [title]}
        item = {"name_eng": "Inception", "year": 2010}
        self.assertEqual(match_item(index, item), title)

    def test_year_mismatch_skips(self):
        index = {"начало": [create_title(name="Начало", release_year=2010)]}
        item = {"name": "Начало", "year": "2015"}
        self.assertIsNone(match_item(index, item))

    def test_no_name_match(self):
        index = {"начало": [create_title(name="Начало", release_year=2010)]}
        item = {"name": "Совсем другой фильм", "year": "2010"}
        self.assertIsNone(match_item(index, item))


class FilterYearsTests(TestCase):
    def test_all_years_known_returns_sorted_set(self):
        index = {
            "a": [SimpleNamespace(release_year=2010)],
            "b": [
                SimpleNamespace(release_year=2021),
                SimpleNamespace(release_year=2010),
            ],
        }
        self.assertEqual(_filter_years(index), [2010, 2021])

    def test_unknown_year_disables_filter(self):
        index = {
            "a": [SimpleNamespace(release_year=2010)],
            "b": [SimpleNamespace(release_year=None)],
        }
        self.assertIsNone(_filter_years(index))

    def test_empty_index_disables_filter(self):
        self.assertIsNone(_filter_years({}))


class SyncVideoServiceIdsTests(TestCase):
    def setUp(self):
        self.movie = create_title(
            name="Начало", original_name="Inception", release_year=2010
        )
        self.series = create_title(name="Игра в кальмара", release_year=2021)

    @staticmethod
    def _fake_links(items):
        def generator(api_key, *, limit=100, updated_from=None, years=None, max_pages=None):
            yield from items

        return generator

    def test_fills_empty_ids_by_original_name(self):
        items = [
            {
                "id": 4427,
                "name": "Начало",
                "name_original": "Inception",
                "type": "movie",
                "year": "2010",
                "kp_id": 27205,
                "imdb_id": "tt1375666",
            }
        ]
        with patch(
            "apps.catalog.video_service_sync.iter_video_links", self._fake_links(items)
        ):
            stats = sync_video_service_ids()

        self.movie.refresh_from_db()
        self.assertEqual(self.movie.kp_id, "27205")
        self.assertEqual(self.movie.imdb_id, "tt1375666")
        self.assertEqual(self.movie.player_id, "4427")
        self.assertEqual(self.movie.player_type, "movie")
        self.assertEqual(stats["fetched"], 1)
        self.assertEqual(stats["matched"], 1)
        self.assertEqual(stats["kp_filled"], 1)
        self.assertEqual(stats["imdb_filled"], 1)
        self.assertEqual(stats["player_filled"], 1)

    def test_player_id_from_embed_code_when_id_differs(self):
        # Внутренний id списка не совпадает с data-id из embed_code:
        # плееру нужен именно data-id (проверено на живых данных).
        items = [
            {
                "id": 871666,
                "name": "Начало",
                "name_rus": "Начало",
                "type": "serial",
                "year": "2010",
                "embed_code": 'data-publisher-id="678503345" data-type="serial" data-id="8285"',
            }
        ]
        with patch(
            "apps.catalog.video_service_sync.iter_video_links", self._fake_links(items)
        ):
            stats = sync_video_service_ids()

        self.movie.refresh_from_db()
        self.assertEqual(self.movie.player_id, "8285")
        self.assertEqual(self.movie.player_type, "series")
        self.assertEqual(stats["player_filled"], 1)

    def test_player_id_falls_back_to_item_id_without_embed_code(self):
        items = [
            {"id": 4427, "name": "Inception", "type": "movie", "year": "2010"}
        ]
        with patch(
            "apps.catalog.video_service_sync.iter_video_links", self._fake_links(items)
        ):
            stats = sync_video_service_ids()

        self.movie.refresh_from_db()
        self.assertEqual(self.movie.player_id, "4427")
        self.assertEqual(stats["player_filled"], 1)

    def test_does_not_clobber_manual_kp_id(self):
        self.movie.kp_id = "999"
        self.movie.save(update_fields=["kp_id"])
        items = [
            {"name": "Inception", "year": "2010", "kp_id": 27205, "imdb_id": "tt1375666"}
        ]
        with patch(
            "apps.catalog.video_service_sync.iter_video_links", self._fake_links(items)
        ):
            stats = sync_video_service_ids()

        self.movie.refresh_from_db()
        self.assertEqual(self.movie.kp_id, "999")
        self.assertEqual(self.movie.imdb_id, "tt1375666")
        self.assertEqual(stats["kp_filled"], 0)
        self.assertEqual(stats["imdb_filled"], 1)

    def test_year_mismatch_is_not_matched(self):
        items = [{"name": "Начало", "year": "2008", "kp_id": 1, "imdb_id": "tt1"}]
        with patch(
            "apps.catalog.video_service_sync.iter_video_links", self._fake_links(items)
        ):
            stats = sync_video_service_ids()

        self.movie.refresh_from_db()
        self.assertEqual(self.movie.kp_id, "")
        self.assertEqual(stats["matched"], 0)
        self.assertEqual(stats["kp_filled"], 0)

    def test_does_not_clobber_manual_player_id(self):
        self.movie.player_id = "999"
        self.movie.player_type = "movie"
        self.movie.save(update_fields=["player_id", "player_type"])
        items = [
            {
                "id": 4427,
                "name": "Inception",
                "type": "serial",
                "year": "2010",
                "kp_id": 27205,
                "imdb_id": "tt1375666",
            }
        ]
        with patch(
            "apps.catalog.video_service_sync.iter_video_links", self._fake_links(items)
        ):
            stats = sync_video_service_ids()

        self.movie.refresh_from_db()
        self.assertEqual(self.movie.player_id, "999")
        self.assertEqual(self.movie.player_type, "movie")
        self.assertEqual(stats["player_filled"], 0)

    def test_fills_serial_type_mapped_to_series(self):
        self.series.player_id = ""
        self.series.save(update_fields=["player_id"])
        items = [
            {
                "id": 8264,
                "name": "Игра в кальмара",
                "type": "serial",
                "year": "2021",
            }
        ]
        with patch(
            "apps.catalog.video_service_sync.iter_video_links", self._fake_links(items)
        ):
            stats = sync_video_service_ids()

        self.series.refresh_from_db()
        self.assertEqual(self.series.player_id, "8264")
        self.assertEqual(self.series.player_type, "series")
        self.assertEqual(stats["player_filled"], 1)

    def test_dry_run_changes_nothing(self):
        items = [{"name": "Inception", "year": "2010", "kp_id": 27205, "imdb_id": "tt1375666"}]
        with patch(
            "apps.catalog.video_service_sync.iter_video_links", self._fake_links(items)
        ):
            sync_video_service_ids(dry_run=True)

        self.movie.refresh_from_db()
        self.assertEqual(self.movie.kp_id, "")
        state = VideoServiceSyncState.get_solo()
        self.assertIsNone(state.last_updated_from)

    def test_incremental_uses_stored_updated_from(self):
        state = VideoServiceSyncState.get_solo()
        state.last_updated_from = timezone.make_aware(datetime(2026, 1, 1))
        state.save(update_fields=["last_updated_from"])

        captured = {}

        def generator(api_key, *, limit=100, updated_from=None, years=None, max_pages=None):
            captured["updated_from"] = updated_from
            captured["years"] = years
            return iter(())

        with patch("apps.catalog.video_service_sync.iter_video_links", generator):
            sync_video_service_ids()

        self.assertEqual(captured["updated_from"], state.last_updated_from)
        # Быстрый путь: годы фильтра берутся из каталога, обе записи их знают.
        self.assertEqual(captured["years"], [2010, 2021])
        state.refresh_from_db()
        self.assertIsNotNone(state.last_updated_from)
        self.assertGreater(
            state.last_updated_from, timezone.make_aware(datetime(2026, 1, 1))
        )

    def test_full_bypasses_stored_updated_from(self):
        state = VideoServiceSyncState.get_solo()
        state.last_updated_from = timezone.make_aware(datetime(2026, 1, 1))
        state.save(update_fields=["last_updated_from"])

        captured = {}

        def generator(api_key, *, limit=100, updated_from=None, years=None, max_pages=None):
            captured["updated_from"] = updated_from
            return iter(())

        with patch("apps.catalog.video_service_sync.iter_video_links", generator):
            sync_video_service_ids(full=True)

        self.assertIsNone(captured["updated_from"])

    def test_no_key_raises(self):
        with override_settings(VIDEO_SERVICE_API_KEY=""):
            with self.assertRaises(VideoServiceAPIError):
                sync_video_service_ids(dry_run=True)


class SyncVideoServiceCommandTests(TestCase):
    def test_raises_without_key(self):
        with override_settings(VIDEO_SERVICE_API_KEY=""):
            with self.assertRaises(CommandError):
                call_command("sync_video_service", dry_run=True)

    def test_reports_statistics(self):
        create_title(name="Начало", original_name="Inception", release_year=2010)
        items = [
            {"name": "Inception", "year": "2010", "kp_id": 27205, "imdb_id": "tt1375666"}
        ]

        def generator(api_key, *, limit=100, updated_from=None, years=None, max_pages=None):
            yield from items

        out = StringIO()
        with patch("apps.catalog.video_service_sync.iter_video_links", generator):
            call_command("sync_video_service", dry_run=True, stdout=out)

        output = out.getvalue()
        self.assertIn("заполнено kp_id: 1", output)
        self.assertIn("сухой прогон", output)


class TitleEnrichmentTests(TestCase):
    """Обогащение записи данными из карточки API при совпадении."""

    def setUp(self):
        self.movie = create_title(
            name="Начало",
            original_name="Inception",
            release_year=2010,
            description="",
            short_description="",
            kp_rating=None,
            imdb_rating=None,
            duration_minutes=None,
        )

    @staticmethod
    def _item(**overrides):
        item = {
            "name": "Inception",
            "year": "2010",
            "description": "Полное описание фильма.",
            "description_short": "Короткая аннотация.",
            "name_original": "Inception",
            "name_eng": "Inception",
            "duration": 148,
            "kp_rating": "8.6",
            "imdb_rating": "8.8",
            "genre": ["Фантастика"],
            "country": ["США"],
        }
        item.update(overrides)
        return item

    def test_fills_empty_enrichable_fields(self):
        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links([self._item()]),
        ):
            stats = sync_video_service_ids()

        self.movie.refresh_from_db()
        self.assertEqual(self.movie.description, "Полное описание фильма.")
        self.assertEqual(self.movie.short_description, "Короткая аннотация.")
        self.assertEqual(self.movie.duration_minutes, 148)
        self.assertEqual(self.movie.kp_rating, Decimal("8.6"))
        self.assertEqual(self.movie.imdb_rating, Decimal("8.8"))
        self.assertEqual(stats["enriched"], 1)

    def test_does_not_clobber_existing_fields(self):
        self.movie.description = "Описание, которое написал редактор."
        self.movie.kp_rating = Decimal("9.9")
        self.movie.save(update_fields=["description", "kp_rating"])

        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links([self._item(description="Другое описание.")]),
        ):
            sync_video_service_ids()

        self.movie.refresh_from_db()
        self.assertEqual(self.movie.description, "Описание, которое написал редактор.")
        self.assertEqual(self.movie.kp_rating, Decimal("9.9"))
        # imdb_rating был пуст — его заполняем, не тронутое не затираем.
        self.assertEqual(self.movie.imdb_rating, Decimal("8.8"))

    def test_skips_invalid_rating_and_duration(self):
        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links(
                [self._item(kp_rating="не рейтинг", duration=0)]
            ),
        ):
            sync_video_service_ids()

        self.movie.refresh_from_db()
        self.assertIsNone(self.movie.kp_rating)
        self.assertIsNone(self.movie.duration_minutes)

    def test_creates_and_links_genres_and_countries(self):
        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links(
                [self._item(genre=["Драма", "Фантастика"], country=["США"])]
            ),
        ):
            stats = sync_video_service_ids()

        self.movie.refresh_from_db()
        self.assertEqual(list(self.movie.genres.values_list("name", flat=True)), ["Драма", "Фантастика"])
        self.assertEqual(list(self.movie.countries.values_list("name", flat=True)), ["США"])
        self.assertEqual(stats["genres_added"], 2)
        self.assertEqual(stats["countries_added"], 1)

    def test_skips_genres_when_title_has_them(self):
        genre = Genre.objects.create(name="Боевик", slug="boevik")
        self.movie.genres.add(genre)

        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links([self._item(genre=["Фантастика"])]),
        ):
            sync_video_service_ids()

        self.movie.refresh_from_db()
        # Ручной набор жанров редактора не трогаем.
        self.assertEqual(list(self.movie.genres.all()), [genre])
        self.assertFalse(Genre.objects.filter(name="Фантастика").exists())

    def test_dry_run_does_not_create_references(self):
        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links([self._item(genre=["Драма"])]),
        ):
            sync_video_service_ids(dry_run=True)

        self.assertEqual(Genre.objects.count(), 0)
        self.assertEqual(Country.objects.count(), 0)

    def _fake_links(self, items):
        def generator(api_key, *, limit=100, updated_from=None, years=None, max_pages=None):
            yield from items

        return generator


class SyncSeriesEpisodesTests(TestCase):
    """Импорт серий сериалов через GET /serials/kp|imdb/{id}."""

    def setUp(self):
        self.serial = create_title(
            name="Игра в кальмара",
            release_year=2021,
            kp_id="4402886",
            player_type="series",
        )
        self.seasons_payload = {
            "id": 871666,
            "name": "Игра в кальмара",
            "seasons": [
                {"name": "1", "series": [{"id": 1, "name": "Пилот"}, {"id": 2, "name": ""}]},
                {"name": "2", "series": [{"id": 3, "name": "Третья серия"}]},
            ],
        }

    def test_creates_episodes_from_seasons(self):
        with patch(
            "apps.catalog.video_service_sync.fetch_serial_by_kp",
            return_value=self.seasons_payload,
        ):
            stats = sync_series_episodes()

        episodes = list(self.serial.episodes.order_by("season_number", "episode_number"))
        self.assertEqual(len(episodes), 3)
        self.assertEqual(
            (episodes[0].season_number, episodes[0].episode_number, episodes[0].name),
            (1, 1, "Пилот"),
        )
        self.assertEqual(
            (episodes[1].season_number, episodes[1].episode_number, episodes[1].name),
            (1, 2, ""),
        )
        self.assertEqual(
            (episodes[2].season_number, episodes[2].episode_number, episodes[2].name),
            (2, 1, "Третья серия"),
        )
        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["created"], 3)
        self.assertEqual(stats["not_found"], 0)
        self.assertEqual(stats["errors"], 0)

    def test_uses_imdb_when_no_kp(self):
        self.serial.kp_id = ""
        self.serial.imdb_id = "tt10919420"
        self.serial.save(update_fields=["kp_id", "imdb_id"])

        with patch(
            "apps.catalog.video_service_sync.fetch_serial_by_imdb",
            return_value=self.seasons_payload,
        ) as fetch:
            sync_series_episodes()

        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[1], "tt10919420")
        self.assertEqual(self.serial.episodes.count(), 3)

    def test_second_run_is_idempotent(self):
        with patch(
            "apps.catalog.video_service_sync.fetch_serial_by_kp",
            return_value=self.seasons_payload,
        ):
            sync_series_episodes()
            stats = sync_series_episodes()

        self.assertEqual(self.serial.episodes.count(), 3)
        self.assertEqual(stats["created"], 0)

    def test_dry_run_writes_nothing(self):
        with patch(
            "apps.catalog.video_service_sync.fetch_serial_by_kp",
            return_value=self.seasons_payload,
        ):
            stats = sync_series_episodes(dry_run=True)

        self.assertEqual(self.serial.episodes.count(), 0)
        self.assertEqual(stats["created"], 3)

    def test_not_found_is_counted_and_skipped(self):
        with patch(
            "apps.catalog.video_service_sync.fetch_serial_by_kp",
            side_effect=VideoServiceNotFoundError("нет записи"),
        ):
            stats = sync_series_episodes()

        self.assertEqual(stats["not_found"], 1)
        self.assertEqual(stats["created"], 0)
        self.assertEqual(self.serial.episodes.count(), 0)

    def test_api_error_is_counted_and_skipped(self):
        with patch(
            "apps.catalog.video_service_sync.fetch_serial_by_kp",
            side_effect=VideoServiceAPIError("API упал"),
        ):
            stats = sync_series_episodes()

        self.assertEqual(stats["errors"], 1)
        self.assertEqual(self.serial.episodes.count(), 0)

    def test_season_name_falls_back_to_index(self):
        payload = {
            "seasons": [
                {"name": "Первый сезон", "series": [{"id": 1, "name": "A"}]},
                {"name": "2", "series": [{"id": 2, "name": "B"}]},
            ]
        }
        with patch(
            "apps.catalog.video_service_sync.fetch_serial_by_kp", return_value=payload
        ):
            sync_series_episodes()

        numbers = list(self.serial.episodes.values_list("season_number", flat=True))
        self.assertEqual(numbers, [1, 2])

    def test_limit_caps_processed_titles(self):
        second = create_title(name="Другой сериал", release_year=2022, kp_id="777")
        with patch(
            "apps.catalog.video_service_sync.fetch_serial_by_kp",
            return_value=self.seasons_payload,
        ):
            stats = sync_series_episodes(limit=1)

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(second.episodes.count(), 0)

    def test_skips_titles_without_external_ids(self):
        create_title(name="Без ID", release_year=2023)
        with patch(
            "apps.catalog.video_service_sync.fetch_serial_by_kp",
            return_value=self.seasons_payload,
        ) as fetch:
            stats = sync_series_episodes()

        self.assertEqual(stats["processed"], 1)
        fetch.assert_called_once()

    def test_skips_titles_that_already_have_episodes(self):
        Episode.objects.create(
            title=self.serial, season_number=1, episode_number=1, name="Пилот"
        )
        with patch(
            "apps.catalog.video_service_sync.fetch_serial_by_kp",
            return_value=self.seasons_payload,
        ) as fetch:
            stats = sync_series_episodes()

        self.assertEqual(stats["processed"], 0)
        fetch.assert_not_called()

    def test_no_key_raises(self):
        with override_settings(VIDEO_SERVICE_API_KEY=""):
            with self.assertRaises(VideoServiceAPIError):
                sync_series_episodes()


class SyncEpisodesCommandTests(TestCase):
    def test_raises_without_key(self):
        with override_settings(VIDEO_SERVICE_API_KEY=""):
            with self.assertRaises(CommandError):
                call_command("sync_episodes", dry_run=True)

    def test_reports_statistics(self):
        create_title(name="Сериал", release_year=2021, kp_id="4402886")
        payload = {"seasons": [{"name": "1", "series": [{"id": 1, "name": "Пилот"}]}]}
        out = StringIO()
        with patch(
            "apps.catalog.video_service_sync.fetch_serial_by_kp", return_value=payload
        ):
            call_command("sync_episodes", dry_run=True, stdout=out)

        output = out.getvalue()
        self.assertIn("создано серий: 1", output)
        self.assertIn("сухой прогон", output)


class VideoServiceAPIClientTests(TestCase):
    @staticmethod
    def _resp(status, payload=None, headers=None):
        response = Mock()
        response.status_code = status
        response.headers = headers or {}
        response.json.return_value = payload
        return response

    def test_fetch_sends_bearer_and_parses(self):
        payload = {"success": True, "data": [{"id": 1}], "meta": {"last_page": 1, "total": 1}}
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = payload
            data, meta = fetch_video_links("secret-key", page=1)

        self.assertEqual(data, [{"id": 1}])
        self.assertEqual(meta["total"], 1)
        call_kwargs = get.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer secret-key")

    def test_fetch_sends_year_filter_as_list(self):
        payload = {"success": True, "data": [], "meta": {"last_page": 1, "total": 0}}
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = payload
            fetch_video_links("secret-key", years=[2014, 2010])

        self.assertEqual(get.call_args.kwargs["params"]["year[]"], [2010, 2014])

    def test_fetch_omits_year_filter_when_not_given(self):
        payload = {"success": True, "data": [], "meta": {"last_page": 1, "total": 0}}
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = payload
            fetch_video_links("secret-key")

        self.assertNotIn("year[]", get.call_args.kwargs["params"])

    def test_http_error_raises(self):
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value.status_code = 500
            with self.assertRaises(VideoServiceAPIError):
                fetch_video_links("secret-key")

    def test_success_false_raises(self):
        payload = {"success": False, "message": "недостаточно прав"}
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = payload
            with self.assertRaises(VideoServiceAPIError):
                fetch_video_links("secret-key")

    def test_iter_paginates_to_last_page(self):
        pages = iter(
            [
                ([{"id": 1}], {"last_page": 2}),
                ([{"id": 2}], {"last_page": 2}),
            ]
        )

        def fake_fetch(api_key, *, page, limit, updated_from, years=None):
            return next(pages)

        with patch("apps.catalog.video_service_api.fetch_video_links", fake_fetch), patch(
            "apps.catalog.video_service_api.time.sleep"
        ):
            got = list(iter_video_links("secret-key"))

        self.assertEqual([item["id"] for item in got], [1, 2])

    def test_iter_forwards_years(self):
        captured = {}

        def fake_fetch(api_key, *, page, limit, updated_from, years=None):
            captured["years"] = years
            return [], {"last_page": 1}

        with patch("apps.catalog.video_service_api.fetch_video_links", fake_fetch):
            list(iter_video_links("secret-key", years=[2001, 1994]))

        self.assertEqual(captured["years"], [2001, 1994])

    def test_max_pages_stops_early(self):
        pages = iter(
            [
                ([{"id": 1}], {"last_page": 10}),
                ([{"id": 2}], {"last_page": 10}),
            ]
        )

        def fake_fetch(api_key, *, page, limit, updated_from, years=None):
            return next(pages)

        with patch("apps.catalog.video_service_api.fetch_video_links", fake_fetch), patch(
            "apps.catalog.video_service_api.time.sleep"
        ):
            got = list(iter_video_links("secret-key", max_pages=2))

        self.assertEqual(len(got), 2)

    def test_retries_on_429_then_succeeds(self):
        with patch("apps.catalog.video_service_api.time.sleep"), patch(
            "apps.catalog.video_service_api.requests.get"
        ) as get:
            get.side_effect = [
                self._resp(429, headers={"Retry-After": "1"}),
                self._resp(
                    200, {"success": True, "data": [{"id": 1}], "meta": {"last_page": 1}}
                ),
            ]
            data, _ = fetch_video_links("secret-key")

        self.assertEqual(data, [{"id": 1}])
        self.assertEqual(get.call_count, 2)

    def test_gives_up_after_persistent_429(self):
        with patch("apps.catalog.video_service_api.time.sleep"), patch(
            "apps.catalog.video_service_api.requests.get"
        ) as get:
            get.return_value = self._resp(429, headers={"Retry-After": "1"})
            with self.assertRaises(VideoServiceAPIError):
                fetch_video_links("secret-key")

        self.assertEqual(get.call_count, MAX_RETRIES)

    def test_fetch_video_by_kp_returns_unwrapped(self):
        payload = {"id": 768755, "name": "Начало", "kp_id": 447301}
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = payload
            video = fetch_video_by_kp("secret-key", 447301)

        self.assertEqual(video["name"], "Начало")
        self.assertEqual(get.call_args.args[0], f"{VIDEO_SERVICE_API_BASE}/videos/kp/447301")

    def test_fetch_video_by_imdb_returns_unwrapped(self):
        payload = {"id": 768755, "imdb_id": "tt1375666"}
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = payload
            video = fetch_video_by_imdb("secret-key", "tt1375666")

        self.assertEqual(video["imdb_id"], "tt1375666")
        self.assertEqual(get.call_args.args[0], f"{VIDEO_SERVICE_API_BASE}/videos/imdb/tt1375666")

    def test_fetch_serial_returns_seasons(self):
        payload = {
            "id": 1,
            "name": "Игра в кальмара",
            "seasons": [{"name": "Сезон 1", "series": [{"id": 1, "name": "Серия 1"}]}],
        }
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = payload
            serial = fetch_serial_by_kp("secret-key", 1301710)

        self.assertEqual(serial["seasons"][0]["name"], "Сезон 1")
        # Сериалы живут на отдельной базе без префикса /publisher.
        self.assertEqual(
            get.call_args.args[0],
            f"{VIDEO_SERVICE_SERIALS_API_BASE}/serials/kp/1301710",
        )

    def test_fetch_serial_by_imdb_path(self):
        payload = {"id": 1, "name": "x", "seasons": None}
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = payload
            fetch_serial_by_imdb("secret-key", "tt10919420")

        self.assertEqual(
            get.call_args.args[0],
            f"{VIDEO_SERVICE_SERIALS_API_BASE}/serials/imdb/tt10919420",
        )

    def test_detail_not_found_raises_specific_error(self):
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value.status_code = 404
            get.return_value.json.side_effect = ValueError("no body")
            with self.assertRaises(VideoServiceNotFoundError):
                fetch_video_by_imdb("secret-key", "tt2543164")


class VideoServiceReferenceListsTests(TestCase):
    """Списковые эндпоинты-справочники: URL, Bearer, разбор обёртки."""

    @staticmethod
    def _resp(data):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"success": True, "data": data}
        return response

    def test_fetch_kpids_parses_and_sends_filters(self):
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value = self._resp([1, 2, 3])
            kpids = fetch_video_kpids(
                "secret-key", content_type="movie", year=2010, page=2, limit=500
            )

        self.assertEqual(kpids, [1, 2, 3])
        self.assertEqual(get.call_args.args[0], f"{VIDEO_SERVICE_API_BASE}/videos/get_kpids")
        self.assertEqual(get.call_args.kwargs["params"]["type"], "movie")
        self.assertEqual(get.call_args.kwargs["params"]["year"], 2010)
        self.assertEqual(get.call_args.kwargs["params"]["page"], 2)
        self.assertEqual(get.call_args.kwargs["params"]["limit"], 500)

    def test_fetch_kpids_defaults(self):
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value = self._resp([])
            fetch_video_kpids("secret-key")

        params = get.call_args.kwargs["params"]
        self.assertNotIn("type", params)
        self.assertNotIn("year", params)
        self.assertEqual(params["limit"], 1000)

    def test_fetch_reference_lists(self):
        cases = [
            ("/videos/categories", fetch_categories, [{"id": 100, "name": "Аниме"}]),
            ("/videos/genres", fetch_genres, [{"id": 100, "name": "комедия", "name_eng": "comedy"}]),
            ("/videos/countries", fetch_countries, [{"id": 100, "name": "Россия", "code": "RU"}]),
            ("/videos/tags", fetch_tags, [{"id": 100, "name": "Новинка", "code": "novinka"}]),
            ("/videos/voiceovers", fetch_voiceovers, [{"id": 4, "name": "LostFilm"}]),
        ]
        for path, fetcher, data in cases:
            with self.subTest(path=path):
                with patch("apps.catalog.video_service_api.requests.get") as get:
                    get.return_value = self._resp(data)
                    got = fetcher("secret-key")

                self.assertEqual(got, data)
                self.assertEqual(get.call_args.args[0], f"{VIDEO_SERVICE_API_BASE}{path}")


class VoiceoverSyncTests(TestCase):
    """Сопоставление озвучек каталога с озвучками сервиса."""

    def setUp(self):
        self.lostfilm = VoiceOver.objects.create(name="LostFilm", slug="lostfilm")
        self.orig = VoiceOver.objects.create(name="Оригинал", slug="original")

    @staticmethod
    def _fake_voiceovers(items):
        return lambda api_key: items

    def test_fills_ids_by_name(self):
        items = [
            {"id": 4, "name": "LostFilm"},
            {"id": 7, "name": "Оригинал"},
            {"id": 9, "name": "Неизвестная студия"},
        ]
        with patch(
            "apps.catalog.video_service_voiceover_sync.fetch_voiceovers",
            self._fake_voiceovers(items),
        ):
            stats = sync_voiceover_ids()

        self.lostfilm.refresh_from_db()
        self.orig.refresh_from_db()
        self.assertEqual(self.lostfilm.vibix_voiceover_id, 4)
        self.assertEqual(self.orig.vibix_voiceover_id, 7)
        self.assertEqual(stats["fetched"], 3)
        self.assertEqual(stats["filled"], 2)

    def test_does_not_clobber_manual_id(self):
        self.lostfilm.vibix_voiceover_id = 999
        self.lostfilm.save(update_fields=["vibix_voiceover_id"])
        items = [{"id": 4, "name": "LostFilm"}]
        with patch(
            "apps.catalog.video_service_voiceover_sync.fetch_voiceovers",
            self._fake_voiceovers(items),
        ):
            stats = sync_voiceover_ids()

        self.lostfilm.refresh_from_db()
        self.assertEqual(self.lostfilm.vibix_voiceover_id, 999)
        self.assertEqual(stats["filled"], 0)

    def test_dry_run_changes_nothing(self):
        items = [{"id": 4, "name": "LostFilm"}]
        with patch(
            "apps.catalog.video_service_voiceover_sync.fetch_voiceovers",
            self._fake_voiceovers(items),
        ):
            stats = sync_voiceover_ids(dry_run=True)

        self.lostfilm.refresh_from_db()
        self.assertIsNone(self.lostfilm.vibix_voiceover_id)
        self.assertEqual(stats["filled"], 1)

    def test_no_key_raises(self):
        with override_settings(VIDEO_SERVICE_API_KEY=""):
            with self.assertRaises(VideoServiceAPIError):
                sync_voiceover_ids(dry_run=True)


class SyncVoiceoversCommandTests(TestCase):
    def test_raises_without_key(self):
        with override_settings(VIDEO_SERVICE_API_KEY=""):
            with self.assertRaises(CommandError):
                call_command("sync_voiceovers", dry_run=True)

    def test_reports_statistics(self):
        VoiceOver.objects.create(name="LostFilm", slug="lostfilm")
        items = [{"id": 4, "name": "LostFilm"}]

        with patch(
            "apps.catalog.video_service_voiceover_sync.fetch_voiceovers",
            lambda api_key: items,
        ):
            out = StringIO()
            call_command("sync_voiceovers", dry_run=True, stdout=out)

        output = out.getvalue()
        self.assertIn("Озвучек от сервиса: 1", output)
        self.assertIn("заполнено сопоставлений: 1", output)
        self.assertIn("сухой прогон", output)


class ImportVoiceoversTests(TestCase):
    """Импорт справочника озвучек из сервиса."""

    @staticmethod
    def _fake_voiceovers(items):
        return lambda api_key: items

    def test_creates_missing_voiceovers(self):
        items = [
            {"id": 4, "name": "LostFilm"},
            {"id": 7, "name": "Оригинал"},
            {"id": 9, "name": "Неизвестная студия"},
        ]
        with patch(
            "apps.catalog.video_service_voiceover_sync.fetch_voiceovers",
            self._fake_voiceovers(items),
        ):
            stats = import_voiceovers_from_service()

        self.assertEqual(stats, {"fetched": 3, "created": 3, "filled": 0})
        self.assertEqual(VoiceOver.objects.count(), 3)
        self.assertEqual(
            VoiceOver.objects.get(name="LostFilm").vibix_voiceover_id, 4
        )
        self.assertEqual(
            VoiceOver.objects.get(name="Неизвестная студия").vibix_voiceover_id, 9
        )

    def test_creates_unique_slugs_for_cyrillic(self):
        items = [{"id": 4, "name": "Оригинал"}, {"id": 5, "name": "Оригинал (UA)"}]
        with patch(
            "apps.catalog.video_service_voiceover_sync.fetch_voiceovers",
            self._fake_voiceovers(items),
        ):
            import_voiceovers_from_service()

        slugs = list(VoiceOver.objects.values_list("slug", flat=True))
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertTrue(all(slugs))

    def test_does_not_duplicate_existing(self):
        VoiceOver.objects.create(name="LostFilm", slug="lostfilm")
        items = [{"id": 4, "name": "LostFilm"}, {"id": 9, "name": "Новая студия"}]
        with patch(
            "apps.catalog.video_service_voiceover_sync.fetch_voiceovers",
            self._fake_voiceovers(items),
        ):
            stats = import_voiceovers_from_service()

        self.assertEqual(stats["created"], 1)
        self.assertEqual(VoiceOver.objects.count(), 2)
        self.assertEqual(
            VoiceOver.objects.get(name="LostFilm").vibix_voiceover_id, 4
        )

    def test_does_not_clobber_manual_id(self):
        existing = VoiceOver.objects.create(name="LostFilm", slug="lostfilm")
        existing.vibix_voiceover_id = 999
        existing.save(update_fields=["vibix_voiceover_id"])
        items = [{"id": 4, "name": "LostFilm"}]
        with patch(
            "apps.catalog.video_service_voiceover_sync.fetch_voiceovers",
            self._fake_voiceovers(items),
        ):
            stats = import_voiceovers_from_service()

        self.assertEqual(stats, {"fetched": 1, "created": 0, "filled": 0})
        existing.refresh_from_db()
        self.assertEqual(existing.vibix_voiceover_id, 999)

    def test_dry_run_changes_nothing(self):
        items = [{"id": 4, "name": "LostFilm"}]
        with patch(
            "apps.catalog.video_service_voiceover_sync.fetch_voiceovers",
            self._fake_voiceovers(items),
        ):
            stats = import_voiceovers_from_service(dry_run=True)

        self.assertEqual(stats["created"], 1)
        self.assertEqual(VoiceOver.objects.count(), 0)


class ImportVoiceoversCommandTests(TestCase):
    def test_raises_without_key(self):
        with override_settings(VIDEO_SERVICE_API_KEY=""):
            with self.assertRaises(CommandError):
                call_command("import_voiceovers", dry_run=True)

    def test_reports_statistics(self):
        items = [{"id": 4, "name": "LostFilm"}]
        with patch(
            "apps.catalog.video_service_voiceover_sync.fetch_voiceovers",
            lambda api_key: items,
        ):
            out = StringIO()
            call_command("import_voiceovers", dry_run=True, stdout=out)

        output = out.getvalue()
        self.assertIn("создано: 1", output)
        self.assertIn("сухой прогон", output)


class SyncVideoServiceTaskTests(TestCase):
    """Планировщик дергает задачу, а не команду: проверяем её поведение."""

    def test_skips_without_api_key(self):
        from apps.catalog.tasks import sync_video_service

        with override_settings(VIDEO_SERVICE_API_KEY=""):
            self.assertIn("пропущена", sync_video_service())

    def test_reports_statistics(self):
        from apps.catalog.tasks import sync_video_service

        stats = {
            "fetched": 10,
            "matched": 3,
            "kp_filled": 2,
            "imdb_filled": 3,
            "player_filled": 2,
        }
        with patch(
            "apps.catalog.video_service_sync.sync_video_service_ids", return_value=stats
        ):
            report = sync_video_service()

        self.assertIn("kp_id 2", report)
        self.assertIn("imdb_id 3", report)
        self.assertIn("player_id 2", report)

    def test_api_error_returns_message(self):
        from apps.catalog.tasks import sync_video_service

        with patch(
            "apps.catalog.video_service_sync.sync_video_service_ids",
            side_effect=VideoServiceAPIError("сервис лежит"),
        ):
            report = sync_video_service()

        self.assertIn("Ошибка синхронизации", report)


class SyncVoiceoversTaskTests(TestCase):
    """Планировщик дергает задачу озвучек, а не команду."""

    def test_skips_without_api_key(self):
        from apps.catalog.tasks import sync_voiceovers

        with override_settings(VIDEO_SERVICE_API_KEY=""):
            self.assertIn("пропущена", sync_voiceovers())

    def test_reports_statistics(self):
        from apps.catalog.tasks import sync_voiceovers

        stats = {"fetched": 10, "filled": 4}
        with patch(
            "apps.catalog.video_service_voiceover_sync.sync_voiceover_ids",
            return_value=stats,
        ):
            report = sync_voiceovers()

        self.assertIn("получено 10", report)
        self.assertIn("заполнено сопоставлений 4", report)

    def test_api_error_returns_message(self):
        from apps.catalog.tasks import sync_voiceovers

        with patch(
            "apps.catalog.video_service_voiceover_sync.sync_voiceover_ids",
            side_effect=VideoServiceAPIError("сервис лежит"),
        ):
            report = sync_voiceovers()

        self.assertIn("Ошибка синхронизации озвучек", report)


class SyncTitleTests(TestCase):
    """sync_title: точечная синхронизация одной записи (sync_vibix --title).

    Клиентский слой замокан на уровне fetch_* функций: сам HTTP к Vibix
    в юнит-тестах не ходим.
    """

    @staticmethod
    def _video_payload(**overrides):
        payload = {
            "id": 501,
            "type": "movie",
            "name": "Начало",
            "name_eng": "Inception",
            "year": 2010,
            "description": "Описание из API",
            "embed_code": '<ins data-publisher-id="1" data-type="movie" data-id="8285">',
        }
        payload.update(overrides)
        return payload

    @staticmethod
    def _serial_payload(**overrides):
        payload = {
            "id": 502,
            "type": "serial",
            "name": "Игра в кальмара",
            "year": 2021,
            "embed_code": '<ins data-publisher-id="1" data-type="series" data-id="8285">',
            "seasons": [
                {"name": "1", "series": [{"name": "Пилот"}, {"name": "Вторая серия"}]}
            ],
        }
        payload.update(overrides)
        return payload

    @patch("apps.catalog.video_service_sync.fetch_video_by_kp")
    def test_movie_fills_player_and_empty_fields(self, fetch):
        fetch.return_value = self._video_payload()
        title = create_title(
            name="Начало",
            original_name="Inception",
            release_year=2010,
            kp_id="4402886",
            description="",
        )

        stats = sync_title(title)
        title.refresh_from_db()

        self.assertEqual(stats["player_filled"], 1)
        self.assertEqual(stats["not_found"], 0)
        self.assertEqual(title.player_id, "8285")
        self.assertEqual(title.player_type, "movie")
        self.assertEqual(title.description, "Описание из API")

    @patch("apps.catalog.video_service_sync.fetch_video_by_kp")
    def test_movie_preserves_existing_fields(self, fetch):
        fetch.return_value = self._video_payload(description="Другое описание")
        title = create_title(kp_id="4402886", description="Уже написанное описание")

        sync_title(title)
        title.refresh_from_db()

        self.assertEqual(title.description, "Уже написанное описание")

    @patch("apps.catalog.video_service_sync.fetch_serial_by_kp")
    def test_series_imports_episodes_once(self, fetch):
        fetch.return_value = self._serial_payload()
        title = create_title(
            name="Игра в кальмара",
            release_year=2021,
            kp_id="5010913",
            type=Title.Type.SERIES,
        )

        stats = sync_title(title)
        title.refresh_from_db()

        self.assertEqual(stats["episodes_created"], 2)
        self.assertEqual(
            list(title.episodes.values_list("season_number", "episode_number")),
            [(1, 1), (1, 2)],
        )
        self.assertEqual(title.episodes.first().name, "Пилот")
        self.assertEqual(title.player_id, "8285")
        self.assertEqual(title.player_type, "series")

        stats_again = sync_title(title)

        self.assertEqual(stats_again["episodes_created"], 0)
        self.assertEqual(title.episodes.count(), 2)

    @patch("apps.catalog.video_service_sync.fetch_video_by_kp")
    def test_not_found_marks_statistics(self, fetch):
        fetch.side_effect = VideoServiceNotFoundError("не найдено")
        title = create_title(kp_id="999999999")

        stats = sync_title(title)
        title.refresh_from_db()

        self.assertEqual(stats["not_found"], 1)
        self.assertEqual(stats["matched"], 0)
        self.assertEqual(title.player_id, "")

    @patch("apps.catalog.video_service_sync.fetch_video_by_kp")
    def test_dry_run_writes_nothing(self, fetch):
        fetch.return_value = self._video_payload()
        title = create_title(kp_id="4402886")

        stats = sync_title(title, dry_run=True)
        title.refresh_from_db()

        self.assertEqual(stats["player_filled"], 1)
        self.assertEqual(title.player_id, "")
        self.assertEqual(title.description, "Описание для теста.")

    def test_without_external_id_rejects(self):
        title = create_title()

        with self.assertRaises(ValueError):
            sync_title(title)

    def test_imdb_id_used_when_no_kp(self):
        with patch(
            "apps.catalog.video_service_sync.fetch_video_by_imdb",
            return_value=self._video_payload(),
        ) as fetch:
            stats = sync_title(create_title(imdb_id="tt1375666"))

        self.assertEqual(stats["player_filled"], 1)
        fetch.assert_called_once()


class SyncVibixCommandTests(TestCase):
    """Команда sync_vibix: проверка аргументов и защиты без ключа API."""

    def test_requires_api_key(self):
        with override_settings(VIBIX_API_TOKEN="", VIDEO_SERVICE_API_KEY=""):
            with self.assertRaises(CommandError):
                call_command("sync_vibix", dry_run=True)

    def test_title_requires_existing_title(self):
        with override_settings(VIBIX_API_TOKEN="test-token"):
            with self.assertRaises(CommandError):
                call_command("sync_vibix", title="no-such-title")

    @patch("apps.catalog.management.commands.sync_vibix.sync_title")
    def test_title_syncs_one_record(self, sync):
        sync.return_value = {"player_filled": 1, "not_found": 0, "enriched": 0, "episodes_created": 0}
        title = create_title(kp_id="4402886")
        out = StringIO()

        call_command("sync_vibix", title=title.slug, stdout=out)

        sync.assert_called_once()
        self.assertEqual(sync.call_args.args[0], title)
        self.assertIn("player_id", out.getvalue())
