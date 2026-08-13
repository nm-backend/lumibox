"""
Тесты синхронизации каталога с API видеосервиса (sync_video_service).

Внешний API не трогаем: HTTP-клиент замокан на уровне requests,
а сама синхронизация — на уровне генератора iter_video_links.
"""

from datetime import datetime
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.catalog.models import VideoServiceSyncState, VoiceOver
from apps.catalog.video_service_api import (
    MAX_RETRIES,
    VIDEO_SERVICE_API_BASE,
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
        self.assertEqual(get.call_args.args[0], f"{VIDEO_SERVICE_API_BASE}/serials/kp/1301710")

    def test_fetch_serial_by_imdb_path(self):
        payload = {"id": 1, "name": "x", "seasons": None}
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = payload
            fetch_serial_by_imdb("secret-key", "tt10919420")

        self.assertEqual(get.call_args.args[0], f"{VIDEO_SERVICE_API_BASE}/serials/imdb/tt10919420")

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
