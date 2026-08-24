"""
Тесты синхронизации каталога с API видеосервиса (sync_video_service).

Внешний API не трогаем: HTTP-клиент замокан на уровне requests,
а сама синхронизация — на уровне генератора iter_video_links.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
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
    VideoServiceAuthenticationError,
    VideoServiceNotFoundError,
    VideoServiceValidationError,
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
    BULK_IMPORT_LOCK_KEY,
    TitleMatchIndex,
    _filter_years,
    bulk_create_from_catalog,
    create_title_from_vibix,
    match_item,
    normalize_name,
    release_bulk_import_lock,
    sync_series_episodes,
    sync_title,
    sync_video_service_ids,
)
from apps.catalog.video_service_voiceover_sync import import_voiceovers_from_service, sync_voiceover_ids
from apps.core.test_factories import create_title


def make_title_index(*titles):
    by_name = {}
    by_kp = {}
    by_imdb = {}
    for title in titles:
        for name in (getattr(title, "name", ""), getattr(title, "original_name", "")):
            normalized = normalize_name(name)
            if normalized:
                by_name.setdefault(normalized, []).append(title)
        kp_id = str(getattr(title, "kp_id", "") or "")
        imdb_id = str(getattr(title, "imdb_id", "") or "").lower()
        if kp_id:
            by_kp.setdefault(kp_id, []).append(title)
        if imdb_id:
            by_imdb.setdefault(imdb_id, []).append(title)
    return TitleMatchIndex(list(titles), by_name, by_kp, by_imdb)


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
        title = create_title(name="Начало", release_year=2010)
        item = {"name": "Начало", "year": "2010", "kp_id": 1, "imdb_id": "tt1"}
        self.assertEqual(match_item(make_title_index(title), item), title)

    def test_matches_by_original_name(self):
        title = create_title(name="Начало", original_name="Inception", release_year=2010)
        item = {"name_eng": "Inception", "year": 2010}
        self.assertEqual(match_item(make_title_index(title), item), title)

    def test_external_id_has_priority_over_name(self):
        exact = create_title(name="Другое название", release_year=2010, kp_id="447301")
        create_title(name="Начало", release_year=2010)

        result = match_item(
            make_title_index(*Title.objects.all()),
            {"name": "Начало", "year": 2010, "kp_id": 447301},
        )

        self.assertEqual(result, exact)

    def test_year_mismatch_skips(self):
        title = create_title(name="Начало", release_year=2010)
        item = {"name": "Начало", "year": "2015"}
        self.assertIsNone(match_item(make_title_index(title), item))

    def test_ambiguous_name_and_year_skips(self):
        first = create_title(name="Одинаковый", release_year=2010)
        second = create_title(name="Одинаковый", release_year=2010)

        self.assertIsNone(
            match_item(
                make_title_index(first, second),
                {"name": "Одинаковый", "year": 2010},
            )
        )

    def test_no_name_match(self):
        title = create_title(name="Начало", release_year=2010)
        item = {"name": "Совсем другой фильм", "year": "2010"}
        self.assertIsNone(match_item(make_title_index(title), item))


class FilterYearsTests(TestCase):
    def test_all_years_known_returns_sorted_set(self):
        index = make_title_index(
            SimpleNamespace(release_year=2010, pk=1),
            SimpleNamespace(release_year=2021, pk=2),
            SimpleNamespace(release_year=2010, pk=3),
        )
        self.assertEqual(_filter_years(index), [2010, 2021])

    def test_unknown_year_disables_filter(self):
        index = make_title_index(
            SimpleNamespace(release_year=2010, pk=1),
            SimpleNamespace(release_year=None, pk=2),
        )
        self.assertIsNone(_filter_years(index))

    def test_empty_index_disables_filter(self):
        self.assertIsNone(_filter_years(TitleMatchIndex([], {}, {}, {})))


@override_settings(VIBIX_API_TOKEN="test-key", VIDEO_SERVICE_API_KEY="test-key")
class SyncVideoServiceIdsTests(TestCase):
    def setUp(self):
        self.movie = create_title(
            name="Начало", original_name="Inception", release_year=2010
        )
        self.series = create_title(name="Игра в кальмара", release_year=2021)

    @staticmethod
    def _fake_links(items):
        def generator(api_key, *, limit=100, updated_from=None, years=None, max_pages=None, content_type=None):
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
                "embed_code": (
                    'data-publisher-id="678503345" data-type="movie" '
                    'data-id="4427"'
                ),
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

    def test_player_id_stays_empty_without_embed_code(self):
        items = [
            {"id": 4427, "name": "Inception", "type": "movie", "year": "2010"}
        ]
        with patch(
            "apps.catalog.video_service_sync.iter_video_links", self._fake_links(items)
        ):
            stats = sync_video_service_ids()

        self.movie.refresh_from_db()
        self.assertEqual(self.movie.player_id, "")
        self.assertEqual(stats["player_filled"], 0)

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
                "embed_code": (
                    'data-publisher-id="678503345" data-type="serial" '
                    'data-id="8264"'
                ),
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
        self.assertFalse(VideoServiceSyncState.objects.exists())

    def test_incremental_uses_stored_updated_from(self):
        state = VideoServiceSyncState.get_solo()
        state.last_updated_from = timezone.make_aware(datetime(2026, 1, 1))
        state.save(update_fields=["last_updated_from"])

        captured = {}

        def generator(api_key, *, limit=100, updated_from=None, years=None, max_pages=None, content_type=None):
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

        def generator(api_key, *, limit=100, updated_from=None, years=None, max_pages=None, content_type=None):
            captured["updated_from"] = updated_from
            return iter(())

        with patch("apps.catalog.video_service_sync.iter_video_links", generator):
            sync_video_service_ids(full=True)

        self.assertIsNone(captured["updated_from"])

    def test_no_key_raises(self):
        with override_settings(VIBIX_API_TOKEN="", VIDEO_SERVICE_API_KEY=""):
            with self.assertRaises(VideoServiceAPIError):
                sync_video_service_ids(dry_run=True)


@override_settings(VIBIX_API_TOKEN="test-key", VIDEO_SERVICE_API_KEY="test-key")
class SyncVideoServiceCommandTests(TestCase):
    def test_raises_without_key(self):
        with override_settings(VIBIX_API_TOKEN="", VIDEO_SERVICE_API_KEY=""):
            with self.assertRaises(CommandError):
                call_command("sync_video_service", dry_run=True)

    def test_reports_statistics(self):
        create_title(name="Начало", original_name="Inception", release_year=2010)
        items = [
            {"name": "Inception", "year": "2010", "kp_id": 27205, "imdb_id": "tt1375666"}
        ]

        def generator(api_key, *, limit=100, updated_from=None, years=None, max_pages=None, content_type=None):
            yield from items

        out = StringIO()
        with patch("apps.catalog.video_service_sync.iter_video_links", generator):
            call_command("sync_video_service", dry_run=True, stdout=out)

        output = out.getvalue()
        self.assertIn("заполнено kp_id: 1", output)
        self.assertIn("сухой прогон", output)


@override_settings(VIBIX_API_TOKEN="test-key", VIDEO_SERVICE_API_KEY="test-key")
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
        def generator(api_key, *, limit=100, updated_from=None, years=None, max_pages=None, content_type=None):
            yield from items

        return generator


@override_settings(VIBIX_API_TOKEN="test-key", VIDEO_SERVICE_API_KEY="test-key")
class SyncSeriesEpisodesTests(TestCase):
    """Импорт серий сериалов через GET /serials/kp|imdb/{id}."""

    def setUp(self):
        self.serial = create_title(
            name="Игра в кальмара",
            type=Title.Type.SERIES,
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
        second = create_title(
            name="Другой сериал",
            type=Title.Type.SERIES,
            release_year=2022,
            kp_id="777",
        )
        with patch(
            "apps.catalog.video_service_sync.fetch_serial_by_kp",
            return_value=self.seasons_payload,
        ):
            stats = sync_series_episodes(limit=1)

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(second.episodes.count(), 0)

    def test_skips_titles_without_external_ids(self):
        create_title(name="Без ID", type=Title.Type.SERIES, release_year=2023)
        with patch(
            "apps.catalog.video_service_sync.fetch_serial_by_kp",
            return_value=self.seasons_payload,
        ) as fetch:
            stats = sync_series_episodes()

        self.assertEqual(stats["processed"], 1)
        fetch.assert_called_once()

    def test_movies_are_not_sent_to_serial_endpoint(self):
        create_title(name="Фильм с ID", type=Title.Type.MOVIE, kp_id="123")
        with patch(
            "apps.catalog.video_service_sync.fetch_serial_by_kp",
            return_value=self.seasons_payload,
        ) as fetch:
            stats = sync_series_episodes()

        self.assertEqual(stats["processed"], 1)
        fetch.assert_called_once_with("test-key", "4402886")

    def test_existing_series_is_refreshed_for_new_episodes(self):
        Episode.objects.create(
            title=self.serial, season_number=1, episode_number=1, name="Пилот"
        )
        with patch(
            "apps.catalog.video_service_sync.fetch_serial_by_kp",
            return_value=self.seasons_payload,
        ) as fetch:
            stats = sync_series_episodes()

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["created"], 2)
        self.assertEqual(self.serial.episodes.count(), 3)
        fetch.assert_called_once_with("test-key", "4402886")

    def test_no_key_raises(self):
        with override_settings(VIBIX_API_TOKEN="", VIDEO_SERVICE_API_KEY=""):
            with self.assertRaises(VideoServiceAPIError):
                sync_series_episodes()


@override_settings(VIBIX_API_TOKEN="test-key", VIDEO_SERVICE_API_KEY="test-key")
class SyncEpisodesCommandTests(TestCase):
    def test_raises_without_key(self):
        with override_settings(VIBIX_API_TOKEN="", VIDEO_SERVICE_API_KEY=""):
            with self.assertRaises(CommandError):
                call_command("sync_episodes", dry_run=True)

    def test_reports_statistics(self):
        create_title(
            name="Сериал",
            type=Title.Type.SERIES,
            release_year=2021,
            kp_id="4402886",
        )
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
        self.assertEqual(call_kwargs["headers"]["Accept"], "application/json")
        self.assertFalse(call_kwargs["allow_redirects"])

    def test_login_redirect_is_authentication_error(self):
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value = self._resp(302, headers={"Location": "/login"})
            with self.assertRaises(VideoServiceAuthenticationError):
                fetch_video_links("expired-token")

        self.assertEqual(get.call_count, 1)

    def test_unauthorized_is_authentication_error(self):
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value = self._resp(401)
            with self.assertRaises(VideoServiceAuthenticationError):
                fetch_video_links("expired-token")

    def test_non_object_json_is_rejected(self):
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value = self._resp(200, [1, 2, 3])
            with self.assertRaises(VideoServiceAPIError):
                fetch_video_links("secret-key")

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
        with patch("apps.catalog.video_service_api.time.sleep"), patch(
            "apps.catalog.video_service_api.requests.get"
        ) as get:
            get.return_value = self._resp(500)
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

        def fake_fetch(api_key, *, page, limit, updated_from, years=None, content_type=None):
            return next(pages)

        with patch("apps.catalog.video_service_api.fetch_video_links", fake_fetch), patch(
            "apps.catalog.video_service_api.time.sleep"
        ):
            got = list(iter_video_links("secret-key"))

        self.assertEqual([item["id"] for item in got], [1, 2])

    def test_iter_forwards_years(self):
        captured = {}

        def fake_fetch(api_key, *, page, limit, updated_from, years=None, content_type=None):
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

        def fake_fetch(api_key, *, page, limit, updated_from, years=None, content_type=None):
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

    def test_invalid_external_ids_are_rejected_before_http(self):
        with patch("apps.catalog.video_service_api.requests.get") as get:
            with self.assertRaises(VideoServiceValidationError):
                fetch_video_by_kp("secret-key", "../../login")
            with self.assertRaises(VideoServiceValidationError):
                fetch_video_by_imdb("secret-key", "not-an-imdb-id")

        get.assert_not_called()


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
            ("/videos/categories", fetch_categories, [{"id": 100, "name": "Фильм"}]),
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


@override_settings(VIBIX_API_TOKEN="test-key", VIDEO_SERVICE_API_KEY="test-key")
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
        with override_settings(VIBIX_API_TOKEN="", VIDEO_SERVICE_API_KEY=""):
            with self.assertRaises(VideoServiceAPIError):
                sync_voiceover_ids(dry_run=True)


@override_settings(VIBIX_API_TOKEN="test-key", VIDEO_SERVICE_API_KEY="test-key")
class SyncVoiceoversCommandTests(TestCase):
    def test_raises_without_key(self):
        with override_settings(VIBIX_API_TOKEN="", VIDEO_SERVICE_API_KEY=""):
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


@override_settings(VIBIX_API_TOKEN="test-key", VIDEO_SERVICE_API_KEY="test-key")
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


@override_settings(VIBIX_API_TOKEN="test-key", VIDEO_SERVICE_API_KEY="test-key")
class ImportVoiceoversCommandTests(TestCase):
    def test_raises_without_key(self):
        with override_settings(VIBIX_API_TOKEN="", VIDEO_SERVICE_API_KEY=""):
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


@override_settings(VIBIX_API_TOKEN="test-key", VIDEO_SERVICE_API_KEY="test-key")
class SyncVideoServiceTaskTests(TestCase):
    """Планировщик дергает задачу, а не команду: проверяем её поведение."""

    def test_skips_without_api_key(self):
        from apps.catalog.tasks import sync_video_service

        with override_settings(VIBIX_API_TOKEN="", VIDEO_SERVICE_API_KEY=""):
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


@override_settings(VIBIX_API_TOKEN="test-key", VIDEO_SERVICE_API_KEY="test-key")
class SyncVoiceoversTaskTests(TestCase):
    """Планировщик дергает задачу озвучек, а не команду."""

    def test_skips_without_api_key(self):
        from apps.catalog.tasks import sync_voiceovers

        with override_settings(VIBIX_API_TOKEN="", VIDEO_SERVICE_API_KEY=""):
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


@override_settings(VIBIX_API_TOKEN="test-key", VIDEO_SERVICE_API_KEY="test-key")
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
        # Живой ответ /serials/kp/{id} не содержит embed_code и type:
        # только id, name и seasons (проверено на реальном API).
        payload = {
            "id": 502,
            "name": "Игра в кальмара",
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

    @patch("apps.catalog.video_service_sync.fetch_video_by_kp")
    @patch("apps.catalog.video_service_sync.fetch_serial_by_kp")
    def test_series_imports_episodes_once(self, fetch_serial, fetch_video):
        # Серии приходят из /serials, а embed (player_id/type) — из /videos:
        # это два разных запроса, потому что /serials не отдаёт embed_code.
        fetch_serial.return_value = self._serial_payload()
        fetch_video.return_value = {
            "id": 871666,
            "type": "serial",
            "name": "Игра в кальмара",
            "year": 2021,
            "embed_code": '<ins data-publisher-id="1" data-type="series" data-id="8285">',
        }
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
        fetch_serial.assert_called_once()
        fetch_video.assert_called_once()

        stats_again = sync_title(title)

        self.assertEqual(stats_again["episodes_created"], 0)
        self.assertEqual(title.episodes.count(), 2)

    @patch("apps.catalog.video_service_sync.fetch_video_by_kp")
    @patch("apps.catalog.video_service_sync.fetch_serial_by_kp")
    def test_series_keeps_episodes_when_video_card_missing(self, fetch_serial, fetch_video):
        # Если /videos/{kp} не находит карточку, серии всё равно импортируются
        # из /serials, а плеер остаётся на kp/imdb-типе без player_id.
        fetch_serial.return_value = self._serial_payload()
        fetch_video.side_effect = VideoServiceNotFoundError("нет карточки")
        title = create_title(
            name="Игра в кальмара",
            release_year=2021,
            kp_id="5010913",
            type=Title.Type.SERIES,
        )

        stats = sync_title(title)
        title.refresh_from_db()

        self.assertEqual(stats["episodes_created"], 2)
        self.assertEqual(stats["matched"], 1)
        self.assertEqual(title.player_id, "")
        self.assertEqual(title.player_type, "")

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

    @patch("apps.catalog.management.commands.sync_vibix.sync_voiceover_ids")
    def test_voiceovers_reports_filled_count(self, sync):
        sync.return_value = {"fetched": 7, "filled": 3}
        out = StringIO()

        call_command("sync_vibix", voiceovers=True, stdout=out)

        sync.assert_called_once_with(dry_run=False)
        self.assertIn("сопоставлено 3", out.getvalue())

    @patch("apps.catalog.management.commands.sync_vibix.sync_series_episodes")
    def test_episodes_syncs_new_seasons(self, sync):
        sync.return_value = {
            "processed": 2,
            "created": 5,
            "not_found": 0,
            "errors": 0,
        }
        out = StringIO()

        call_command("sync_vibix", episodes=True, limit=2, stdout=out)

        sync.assert_called_once_with(dry_run=False, limit=2)
        self.assertIn("создано серий 5", out.getvalue())

    def test_limit_requires_episodes_mode(self):
        with self.assertRaises(CommandError):
            call_command("sync_vibix", limit=1)


@override_settings(VIBIX_API_TOKEN="test-token")
class CreateTitleFromVibixTests(TestCase):
    """create_title_from_vibix: создание записи каталога из карточки API.

    API не трогаем — fetch_video_by_kp замокан на уровне модуля синхронизации.
    """

    def _detail(self, **overrides):
        item = {
            "id": 990001,
            "name": "Inception",
            "name_rus": "Начало",
            "name_eng": "Inception",
            "name_original": "Inception",
            "type": "movie",
            "year": "2010",
            "kp_id": 447301,
            "imdb_id": "tt1375666",
            "kp_rating": "8.6",
            "imdb_rating": "8.8",
            "duration": 148,
            "description": "Вор проникает в чужие сны, чтобы внедрить идею.",
            "description_short": "Кража идей во сне.",
            "embed_code": 'data-publisher-id="678822630" data-type="movie" data-id="4427"',
            "genre": ["Фантастика", "Триллер"],
            "country": ["США", "Великобритания"],
        }
        item.update(overrides)
        return item

    def _patch(self, item):
        return patch(
            "apps.catalog.video_service_sync.fetch_video_by_kp",
            return_value=item,
        )

    def test_creates_published_title_with_metadata(self):
        with self._patch(self._detail()):
            title, outcome = create_title_from_vibix("test-token", "447301")

        self.assertEqual(outcome, "created")
        self.assertIsNotNone(title)
        title.refresh_from_db()
        self.assertEqual(title.name, "Начало")
        self.assertEqual(title.original_name, "Inception")
        self.assertEqual(title.release_year, 2010)
        self.assertEqual(title.kp_id, "447301")
        self.assertEqual(title.imdb_id, "tt1375666")
        self.assertEqual(title.status, Title.Status.PUBLISHED)
        self.assertIsNotNone(title.published_at)
        self.assertEqual(title.type, Title.Type.MOVIE)
        # player_id берётся из data-id embed_code, а не из внутреннего item.id.
        self.assertEqual(title.player_id, "4427")
        self.assertEqual(title.player_type, "movie")
        self.assertEqual(title.description, "Вор проникает в чужие сны, чтобы внедрить идею.")
        self.assertEqual(title.duration_minutes, 148)
        self.assertEqual(title.kp_rating, Decimal("8.6"))
        self.assertEqual(title.imdb_rating, Decimal("8.8"))
        self.assertEqual(
            sorted(title.genres.values_list("name", flat=True)),
            ["Триллер", "Фантастика"],
        )
        self.assertEqual(
            sorted(title.countries.values_list("name", flat=True)),
            ["Великобритания", "США"],
        )
        self.assertTrue(title.slug)

    def test_serial_type_maps_to_series(self):
        with self._patch(self._detail(type="serial")):
            title, outcome = create_title_from_vibix("test-token", "447301")

        self.assertEqual(outcome, "created")
        self.assertEqual(title.type, Title.Type.SERIES)

    def test_existing_kp_id_is_not_duplicated(self):
        existing = create_title(name="Уже в базе", kp_id="447301")

        with self._patch(self._detail()) as mock_fetch:
            title, outcome = create_title_from_vibix("test-token", "447301")

        self.assertEqual(outcome, "exists")
        self.assertEqual(title.pk, existing.pk)
        # Существующий kp_id — сразу выход, к API не обращаемся.
        mock_fetch.assert_not_called()
        self.assertEqual(Title.objects.filter(kp_id="447301").count(), 1)

    def test_not_found_returns_outcome(self):
        with patch(
            "apps.catalog.video_service_sync.fetch_video_by_kp",
            side_effect=VideoServiceNotFoundError("нет записи"),
        ):
            title, outcome = create_title_from_vibix("test-token", "999999")

        self.assertIsNone(title)
        self.assertEqual(outcome, "not_found")
        self.assertFalse(Title.objects.filter(kp_id="999999").exists())

    def test_missing_year_is_skipped(self):
        with self._patch(self._detail(year=None)):
            title, outcome = create_title_from_vibix("test-token", "447301")

        self.assertIsNone(title)
        self.assertEqual(outcome, "no_year")
        self.assertFalse(Title.objects.filter(kp_id="447301").exists())

    def test_missing_name_is_skipped(self):
        with self._patch(self._detail(name="", name_rus="", name_eng="")):
            title, outcome = create_title_from_vibix("test-token", "447301")

        self.assertIsNone(title)
        self.assertEqual(outcome, "no_name")

    def test_dry_run_creates_nothing(self):
        with self._patch(self._detail()):
            title, outcome = create_title_from_vibix("test-token", "447301", dry_run=True)

        self.assertIsNone(title)
        self.assertEqual(outcome, "created")
        self.assertFalse(Title.objects.filter(kp_id="447301").exists())


@override_settings(VIBIX_API_TOKEN="test-token")
class CreateFromVibixCommandTests(TestCase):
    """Команда create_from_vibix: аргументы, отчёт, идемпотентность."""

    def _detail(self, kp_id, name, year):
        return {
            "name_rus": name,
            "type": "movie",
            "year": str(year),
            "kp_id": kp_id,
            "imdb_id": "",
            "embed_code": f'data-type="movie" data-id="{kp_id}"',
            "genre": [],
            "country": [],
        }

    def test_creates_titles_from_arguments(self):
        details = {
            "447301": self._detail("447301", "Начало", 2010),
            "258687": self._detail("258687", "Интерстеллар", 2014),
        }
        out = StringIO()
        with patch(
            "apps.catalog.video_service_sync.fetch_video_by_kp",
            side_effect=lambda key, kp_id: details[str(kp_id)],
        ):
            call_command("create_from_vibix", "447301", "258687", stdout=out)

        self.assertTrue(Title.objects.filter(kp_id="447301").exists())
        self.assertTrue(Title.objects.filter(kp_id="258687").exists())
        self.assertIn("создано: 2", out.getvalue())

    def test_duplicate_ids_processed_once(self):
        detail = self._detail("447301", "Начало", 2010)
        with patch(
            "apps.catalog.video_service_sync.fetch_video_by_kp",
            return_value=detail,
        ) as mock_fetch:
            call_command("create_from_vibix", "447301", "447301", "447301", stdout=StringIO())

        self.assertEqual(Title.objects.filter(kp_id="447301").count(), 1)
        # Дубли ID схлопываются до запроса к API.
        self.assertEqual(mock_fetch.call_count, 1)

    def test_rerun_is_idempotent(self):
        detail = self._detail("447301", "Начало", 2010)
        with patch(
            "apps.catalog.video_service_sync.fetch_video_by_kp",
            return_value=detail,
        ):
            call_command("create_from_vibix", "447301", stdout=StringIO())
            out = StringIO()
            call_command("create_from_vibix", "447301", stdout=out)

        self.assertEqual(Title.objects.filter(kp_id="447301").count(), 1)
        self.assertIn("уже было: 1", out.getvalue())

    def test_dry_run_writes_nothing(self):
        detail = self._detail("447301", "Начало", 2010)
        out = StringIO()
        with patch(
            "apps.catalog.video_service_sync.fetch_video_by_kp",
            return_value=detail,
        ):
            call_command("create_from_vibix", "447301", "--dry-run", stdout=out)

        self.assertFalse(Title.objects.filter(kp_id="447301").exists())
        self.assertIn("ничего не записано", out.getvalue())

    def test_no_ids_raises(self):
        with self.assertRaises(CommandError):
            call_command("create_from_vibix", stdout=StringIO())

    @override_settings(VIBIX_API_TOKEN="", VIDEO_SERVICE_API_KEY="")
    def test_missing_token_raises(self):
        with self.assertRaises(CommandError):
            call_command("create_from_vibix", "447301", stdout=StringIO())


class TitleKpIdUniquenessTests(TestCase):
    """Частичный уникальный индекс по kp_id: дублей нет на уровне БД."""

    def test_duplicate_kp_id_rejected(self):
        create_title(name="Первая", kp_id="447301")
        with self.assertRaises(IntegrityError):
            Title.objects.create(name="Вторая", slug="vtoraya", kp_id="447301")

    def test_empty_kp_ids_are_not_unique(self):
        create_title(name="Без ID раз", kp_id="")
        create_title(name="Без ID два", kp_id="")
        self.assertEqual(Title.objects.filter(kp_id="").count(), 2)


class VideoLinkTypeFilterTests(TestCase):
    """Серверный фильтр type для раздельного обхода фильмов и сериалов."""

    @staticmethod
    def _ok_payload():
        return {"success": True, "data": [], "meta": {"last_page": 1, "total": 0}}

    def test_fetch_sends_type_filter(self):
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = self._ok_payload()
            fetch_video_links("secret-key", content_type="serial")

        self.assertEqual(get.call_args.kwargs["params"]["type"], "serial")

    def test_fetch_omits_type_filter_when_not_given(self):
        with patch("apps.catalog.video_service_api.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = self._ok_payload()
            fetch_video_links("secret-key")

        self.assertNotIn("type", get.call_args.kwargs["params"])

    def test_invalid_type_rejected_before_request(self):
        with patch("apps.catalog.video_service_api.requests.get") as get:
            with self.assertRaises(VideoServiceValidationError):
                fetch_video_links("secret-key", content_type="cartoon")

        get.assert_not_called()

    def test_iter_forwards_type_to_pages(self):
        pages = iter(
            [
                self._ok_payload(),
                self._ok_payload(),
            ]
        )

        def fake_get(url, **kwargs):
            try:
                response = Mock()
                response.status_code = 200
                response.json.return_value = next(pages)
                return response
            except StopIteration:
                self.fail("iter_video_links запросил больше страниц, чем ожидалось")

        with patch("apps.catalog.video_service_api.time.sleep"), patch(
            "apps.catalog.video_service_api.requests.get", side_effect=fake_get
        ):
            items = list(
                iter_video_links("secret-key", limit=100, content_type="movie")
            )

        self.assertEqual(items, [])


def make_catalog_item(**overrides):
    """Карточка списка /publisher/videos/links с полями из живого OpenAPI."""
    item = {
        "id": 4427,
        "name": "Inception",
        "name_rus": "Начало",
        "name_original": "Inception",
        "type": "movie",
        "year": "2010",
        "kp_id": 27205,
        "imdb_id": "tt1375666",
        "kp_rating": "8.6",
        "imdb_rating": "8.8",
        "quality": "WEB-DL",
        "duration": 148,
        "description": "Описание фильма",
        "poster_url": "https://cdn.example/poster.jpg",
        "backdrop_url": "",
        "genre": ["фантастика", "триллер"],
        "country": ["США"],
        "embed_code": (
            'data-publisher-id="678503345" data-type="movie" data-id="4427"'
        ),
    }
    item.update(overrides)
    return item


@override_settings(VIBIX_API_TOKEN="test-key", VIDEO_SERVICE_API_KEY="test-key")
class BulkCreateFromCatalogTests(TestCase):
    """Массовый импорт: батчи, дедуп по kp_id, dry-run, блокировка."""

    @staticmethod
    def _fake_links(items):
        def generator(api_key, *, limit=100, updated_from=None, years=None, max_pages=None, content_type=None):
            yield from items

        return generator

    def test_creates_drafts_with_metadata_and_references(self):
        items = [
            make_catalog_item(),
            make_catalog_item(
                id=8285,
                name_rus="Игра в кальмара",
                name="Squid Game",
                name_original="Squid Game",
                type="serial",
                year=2021,
                kp_id=56835,
                imdb_id="tt10919420",
                quality="4K",
                embed_code='data-type="serial" data-id="8285"',
            ),
        ]

        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links(items),
        ):
            stats = bulk_create_from_catalog()

        self.assertEqual(stats["created"], 2)
        self.assertEqual(stats["fetched"], 2)
        self.assertEqual(Title.objects.count(), 2)

        movie = Title.objects.get(kp_id="27205")
        self.assertEqual(movie.status, Title.Status.DRAFT)
        self.assertIsNone(movie.published_at)
        self.assertEqual(movie.slug, "inception-2010")
        self.assertEqual(movie.player_id, "4427")
        self.assertEqual(movie.player_type, "movie")
        self.assertEqual(movie.quality, Title.Quality.WEB_DL)
        self.assertEqual(movie.description, "Описание фильма")
        self.assertEqual(movie.poster_url, "https://cdn.example/poster.jpg")
        self.assertEqual(movie.backdrop_url, "")
        self.assertEqual(movie.kp_rating, Decimal("8.6"))
        self.assertCountEqual(
            movie.genres.values_list("name", flat=True), ["фантастика", "триллер"]
        )
        self.assertCountEqual(
            movie.countries.values_list("name", flat=True), ["США"]
        )
        # Кириллические названия жанров транслитерации не получают —
        # адрес уходит на фолбэк, главное что он латиница и не пустой.
        for genre in Genre.objects.all():
            self.assertTrue(genre.slug and genre.slug.isascii())

        series = Title.objects.get(kp_id="56835")
        self.assertEqual(series.type, Title.Type.SERIES)
        # Некаталожное значение качества не попадает в запись.
        self.assertEqual(series.quality, "")
        # Кириллическое название транслитерируется.
        self.assertEqual(series.slug, "squid-game-2021")
        self.assertEqual(series.player_id, "8285")
        self.assertEqual(series.player_type, "series")

    def test_slug_collision_within_run_gets_suffix(self):
        items = [
            make_catalog_item(),
            make_catalog_item(id=4428, kp_id=27206),
        ]
        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links(items),
        ):
            stats = bulk_create_from_catalog()

        self.assertEqual(stats["created"], 2)
        slugs = set(Title.objects.values_list("slug", flat=True))
        self.assertEqual(len(slugs), 2)
        self.assertIn("inception-2010-2", slugs)

    def test_rerun_is_idempotent(self):
        items = [make_catalog_item(), make_catalog_item(id=8285, kp_id=56835)]

        for _ in range(2):
            with patch(
                "apps.catalog.video_service_sync.iter_video_links",
                self._fake_links(items),
            ):
                stats = bulk_create_from_catalog()

        self.assertEqual(Title.objects.count(), 2)
        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["skipped_existing"], 2)

    def test_resume_after_interrupted_import(self):
        # Первый прогон упал после одной карточки (эмуляция обрыва),
        # второй проходит весь список: докидывает только недостающее.
        first = [make_catalog_item()]
        full = [
            make_catalog_item(),
            make_catalog_item(id=8285, kp_id=56835, name_rus="Игра в кальмара", name="Squid Game"),
        ]
        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links(first),
        ):
            bulk_create_from_catalog()

        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links(full),
        ):
            stats = bulk_create_from_catalog()

        self.assertEqual(Title.objects.count(), 2)
        self.assertEqual(stats["created"], 1)
        self.assertEqual(stats["skipped_existing"], 1)

    def test_dry_run_counts_without_writing(self):
        items = [make_catalog_item(), make_catalog_item(id=8285, kp_id=56835)]
        seen = []

        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links(items),
        ):
            stats = bulk_create_from_catalog(dry_run=True, progress=seen.append)

        self.assertEqual(stats["created"], 2)
        self.assertEqual(Title.objects.count(), 0)
        self.assertFalse(Genre.objects.exists())
        # Финальный слепок счётчиков дошёл до колбэка.
        self.assertEqual(seen[-1]["created"], 2)

    def test_batches_flush_by_batch_size(self):
        items = [
            make_catalog_item(id=index, kp_id=index, name_rus=f"Фильм {index}", name=f"Film {index}")
            for index in range(1, 6)
        ]
        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links(items),
        ):
            stats = bulk_create_from_catalog(batch_size=2)

        self.assertEqual(stats["created"], 5)
        self.assertEqual(stats["batches"], 3)  # 2 + 2 + 1
        self.assertEqual(Title.objects.count(), 5)

    def test_race_fallback_saves_records_one_by_one(self):
        # Другой процесс вставил часть батча между нашим снимком kp_id и
        # записью: bulk_create падает целиком, спасение — по одной записи.
        items = [
            make_catalog_item(),
            make_catalog_item(id=8285, kp_id=56835, name_rus="Игра в кальмара", name="Squid Game"),
        ]
        real_bulk_create = Title.objects.bulk_create
        attempts = {"count": 0}

        def flaky_bulk_create(*args, **kwargs):
            if attempts["count"] == 0:
                attempts["count"] += 1
                raise IntegrityError("title_kp_id_uniq_when_filled")
            return real_bulk_create(*args, **kwargs)

        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links(items),
        ), patch.object(Title.objects, "bulk_create", side_effect=flaky_bulk_create):
            stats = bulk_create_from_catalog()

        self.assertEqual(attempts["count"], 1)
        self.assertEqual(Title.objects.count(), 2)
        self.assertEqual(stats["created"], 2)

    def test_reference_link_failure_does_not_miscount_created_rows(self):
        # Регрессия: сбой связки жанров после успешной вставки батча раньше
        # приводил к тому, что созданные записи считались дублями.
        items = [make_catalog_item(), make_catalog_item(id=8285, kp_id=56835)]
        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links(items),
        ), patch.object(
            Title.genres.through.objects,
            "bulk_create",
            side_effect=IntegrityError("жанровая гонка"),
        ):
            stats = bulk_create_from_catalog()

        self.assertEqual(stats["created"], 2)
        self.assertEqual(stats["skipped_existing"], 0)
        self.assertEqual(Title.objects.count(), 2)

    def test_lock_blocks_parallel_run(self):
        state, _ = VideoServiceSyncState.objects.get_or_create(key=BULK_IMPORT_LOCK_KEY)
        state.locked_at = timezone.now()
        state.save(update_fields=["locked_at"])

        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links([make_catalog_item()]),
        ):
            with self.assertRaises(VideoServiceAPIError):
                bulk_create_from_catalog()

        self.assertEqual(Title.objects.count(), 0)

    def test_stale_lock_is_overridden(self):
        state, _ = VideoServiceSyncState.objects.get_or_create(key=BULK_IMPORT_LOCK_KEY)
        state.locked_at = timezone.now() - timedelta(hours=13)
        state.save(update_fields=["locked_at"])

        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links([make_catalog_item()]),
        ):
            stats = bulk_create_from_catalog()

        self.assertEqual(stats["created"], 1)

    def test_lock_released_after_success_and_after_crash(self):
        items = [make_catalog_item()]

        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links(items),
        ):
            bulk_create_from_catalog()
        self.assertIsNone(
            VideoServiceSyncState.objects.get(key=BULK_IMPORT_LOCK_KEY).locked_at
        )

        def exploding_generator(api_key, **kwargs):
            yield make_catalog_item(id=99, kp_id=999999)
            raise RuntimeError("обрыв соединения")

        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            exploding_generator,
        ):
            with self.assertRaises(RuntimeError):
                bulk_create_from_catalog()
        self.assertIsNone(
            VideoServiceSyncState.objects.get(key=BULK_IMPORT_LOCK_KEY).locked_at
        )

    def test_release_bulk_import_lock(self):
        state, _ = VideoServiceSyncState.objects.get_or_create(key=BULK_IMPORT_LOCK_KEY)
        state.locked_at = timezone.now()
        state.save(update_fields=["locked_at"])

        self.assertTrue(release_bulk_import_lock())
        self.assertFalse(release_bulk_import_lock())
        self.assertIsNone(
            VideoServiceSyncState.objects.get(key=BULK_IMPORT_LOCK_KEY).locked_at
        )

    def test_invalid_status_and_type_raise(self):
        with self.assertRaises(ValueError):
            bulk_create_from_catalog(status="archived")
        with self.assertRaises(ValueError):
            bulk_create_from_catalog(content_type="cartoon")

    def test_missing_items_are_counted_with_samples(self):
        items = [
            make_catalog_item(kp_id="", name_rus="Нет ID"),
            make_catalog_item(id=2, kp_id=2, name_rus="", name="", name_original="NoName"),
            make_catalog_item(id=3, kp_id=3, name_rus="Без года", year=""),
        ]
        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links(items),
        ):
            stats = bulk_create_from_catalog()

        self.assertEqual(stats["no_kp_id"], 1)
        self.assertEqual(stats["no_name"], 1)
        self.assertEqual(stats["no_year"], 1)
        self.assertEqual(stats["samples_no_name"], ["NoName"])
        self.assertEqual(stats["samples_no_year"], ["Без года"])
        self.assertEqual(Title.objects.count(), 0)


@override_settings(VIBIX_API_TOKEN="test-key", VIDEO_SERVICE_API_KEY="test-key")
class CreateMissingCommandTests(TestCase):
    """Команда sync_vibix --create-missing: отчёт, dry-run, валидация флагов."""

    @staticmethod
    def _fake_links(items):
        def generator(api_key, *, limit=100, updated_from=None, years=None, max_pages=None, content_type=None):
            yield from items

        return generator

    def test_dry_run_prints_plan_and_writes_nothing(self):
        items = [make_catalog_item()]
        out = StringIO()
        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links(items),
        ):
            call_command(
                "sync_vibix", "--create-missing", "--dry-run", "--max-pages", "1",
                stdout=out,
            )

        self.assertEqual(Title.objects.count(), 0)
        text = out.getvalue()
        self.assertIn("будет создано 1", text)
        self.assertIn("ничего не записано", text)

    def test_published_status_sets_published_at(self):
        items = [make_catalog_item()]
        with patch(
            "apps.catalog.video_service_sync.iter_video_links",
            self._fake_links(items),
        ):
            call_command("sync_vibix", "--create-missing", "--status", "published", stdout=StringIO())

        title = Title.objects.get(kp_id="27205")
        self.assertEqual(title.status, Title.Status.PUBLISHED)
        self.assertIsNotNone(title.published_at)

    def test_type_filter_passed_to_api_layer(self):
        captured = {}

        def generator(api_key, *, content_type=None, **kwargs):
            captured["content_type"] = content_type
            return iter([])

        with patch("apps.catalog.video_service_sync.iter_video_links", generator):
            call_command("sync_vibix", "--create-missing", "--type", "serial", stdout=StringIO())

        self.assertEqual(captured["content_type"], "serial")

    def test_flags_require_create_missing(self):
        for args in (
            ["--status", "published"],
            ["--batch-size", "100"],
            ["--type", "serial"],
        ):
            with self.assertRaises(CommandError):
                call_command("sync_vibix", *args, stdout=StringIO())

    def test_modes_are_mutually_exclusive(self):
        with self.assertRaises(CommandError):
            call_command("sync_vibix", "--create-missing", "--episodes", stdout=StringIO())

    def test_unlock_releases_lock(self):
        state, _ = VideoServiceSyncState.objects.get_or_create(key=BULK_IMPORT_LOCK_KEY)
        state.locked_at = timezone.now()
        state.save(update_fields=["locked_at"])

        call_command("sync_vibix", "--unlock", stdout=StringIO())
        state.refresh_from_db()
        self.assertIsNone(state.locked_at)

    def test_unlock_rejects_other_modes(self):
        with self.assertRaises(CommandError):
            call_command("sync_vibix", "--unlock", "--create-missing", stdout=StringIO())


@override_settings(VIBIX_API_TOKEN="test-key", VIDEO_SERVICE_API_KEY="test-key")
class CreateMissingCatalogTaskTests(TestCase):
    """Celery-задача массового импорта: отчёт строкой, ошибки не роняют."""

    def test_skips_without_api_key(self):
        from apps.catalog.tasks import create_missing_catalog

        with override_settings(VIBIX_API_TOKEN="", VIDEO_SERVICE_API_KEY=""):
            self.assertIn("пропущен", create_missing_catalog())

    def test_reports_statistics(self):
        from apps.catalog.tasks import create_missing_catalog

        stats = {
            "fetched": 10, "created": 7, "skipped_existing": 3, "errors": 0,
            "genres_created": 0, "countries_created": 0, "batches": 1,
            "no_kp_id": 0, "no_name": 0, "no_year": 0,
            "samples_no_name": [], "samples_no_year": [], "errors_log": [],
        }
        with patch(
            "apps.catalog.video_service_sync.bulk_create_from_catalog",
            return_value=stats,
        ) as run:
            report = create_missing_catalog()

        run.assert_called_once()
        self.assertIn("создано 7", report)
        self.assertIn("уже было 3", report)

    def test_api_error_returns_message(self):
        from apps.catalog.tasks import create_missing_catalog

        with patch(
            "apps.catalog.video_service_sync.bulk_create_from_catalog",
            side_effect=VideoServiceAPIError("блокировка активна"),
        ):
            report = create_missing_catalog()

        self.assertIn("Ошибка массового импорта", report)
