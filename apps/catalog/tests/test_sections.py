"""
Тесты разделов-витрин, расширенных фильтров и франшиз.

Все разделы — тот же каталог с суженной выборкой: они наследуют
TitleListView и трогают только get_base_queryset(). Поэтому здесь
проверяется не отрисовка (её стережёт test_views), а состав и порядок.
"""

from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Franchise, PlaybackSource, Title, VoiceOver
from apps.catalog.tests.test_episodes import create_episode, create_source
from apps.core.test_factories import create_genre, create_review, create_title


def names(response):
    """Названия записей в выдаче — по ним удобно сверять состав и порядок."""
    return [title.name for title in response.context["titles"]]


class SectionViewTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_new_section_orders_by_publication(self):
        first = create_title(name="Опубликован раньше")
        second = create_title(name="Опубликован позже")
        # published_at проставляется при сохранении, поэтому разводим явно.
        Title.objects.filter(pk=first.pk).update(published_at=timezone.now() - timedelta(days=5))
        Title.objects.filter(pk=second.pk).update(published_at=timezone.now())

        response = self.client.get(reverse("catalog:new"))

        self.assertEqual(names(response), ["Опубликован позже", "Опубликован раньше"])

    def test_popular_section_orders_by_views(self):
        quiet = create_title(name="Мало смотрят")
        loud = create_title(name="Много смотрят")
        Title.objects.filter(pk=quiet.pk).update(views_count=3)
        Title.objects.filter(pk=loud.pk).update(views_count=300)

        response = self.client.get(reverse("catalog:popular"))

        self.assertEqual(names(response)[0], "Много смотрят")

    def test_top_section_shows_only_rated(self):
        rated = create_title(name="С оценкой")
        create_review(title=rated, rating=9)
        create_title(name="Без оценки")

        response = self.client.get(reverse("catalog:top"))

        self.assertEqual(names(response), ["С оценкой"])

    def test_premieres_shows_only_future_releases(self):
        create_title(name="Уже вышел", release_date=timezone.localdate() - timedelta(days=1))
        create_title(name="Ещё выйдет", release_date=timezone.localdate() + timedelta(days=30))
        create_title(name="Дата неизвестна")

        response = self.client.get(reverse("catalog:premieres"))

        self.assertEqual(names(response), ["Ещё выйдет"])

    def test_year_section_filters_by_year(self):
        create_title(name="Из 2019", release_year=2019)
        create_title(name="Из 2021", release_year=2021)

        response = self.client.get(reverse("catalog:year_titles", args=[2019]))

        self.assertEqual(names(response), ["Из 2019"])

    def test_sections_hide_drafts(self):
        create_title(name="Черновик раздела", status=Title.Status.DRAFT)

        for name in ["new", "popular", "top", "premieres"]:
            with self.subTest(section=name):
                response = self.client.get(reverse(f"catalog:{name}"))
                self.assertNotIn("Черновик раздела", names(response))

    def test_section_keeps_filters_and_sorting(self):
        """Раздел — это каталог: фильтры и сортировка в нём обязаны работать."""
        create_title(name="Фильм раздела", type=Title.Type.MOVIE)
        create_title(name="Сериал раздела", type=Title.Type.SERIES)

        response = self.client.get(reverse("catalog:new"), {"type": "series"})

        self.assertEqual(names(response), ["Сериал раздела"])


class ExtendedFilterTests(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse("catalog:title_list")

    def tearDown(self):
        cache.clear()

    def test_year_range(self):
        create_title(name="Старое", release_year=1999)
        create_title(name="Среднее", release_year=2010)
        create_title(name="Новое", release_year=2022)

        response = self.client.get(self.url, {"year_from": 2005, "year_to": 2015})

        self.assertEqual(names(response), ["Среднее"])

    def test_year_range_open_ended(self):
        create_title(name="Старое", release_year=1999)
        create_title(name="Новое", release_year=2022)

        response = self.client.get(self.url, {"year_from": 2000})

        self.assertEqual(names(response), ["Новое"])

    def test_rating_from(self):
        good = create_title(name="Хороший")
        create_review(title=good, rating=9)
        weak = create_title(name="Слабый")
        create_review(title=weak, rating=3)

        response = self.client.get(self.url, {"rating_from": "7"})

        self.assertEqual(names(response), ["Хороший"])

    def test_quality(self):
        create_title(name="В хорошем качестве", quality=Title.Quality.WEB_DL)
        create_title(name="С экранки", quality=Title.Quality.CAMRIP)

        response = self.client.get(self.url, {"quality": Title.Quality.WEB_DL})

        self.assertEqual(names(response), ["В хорошем качестве"])

    def test_age_rating(self):
        create_title(name="Для всех", age_rating=Title.AgeRating.EVERYONE)
        create_title(name="Для взрослых", age_rating=Title.AgeRating.ADULT)

        response = self.client.get(self.url, {"age_rating": Title.AgeRating.ADULT})

        self.assertEqual(names(response), ["Для взрослых"])

    def test_voice(self):
        voice = VoiceOver.objects.create(name="Дубляж", slug="dubbed")
        dubbed = create_title(name="С дубляжом", type=Title.Type.SERIES)
        create_source(create_episode(dubbed, with_source=False), voice=voice)
        create_title(name="Без дубляжа")

        response = self.client.get(self.url, {"voice": "dubbed"})

        self.assertEqual(names(response), ["С дубляжом"])

    def test_voice_does_not_duplicate_rows(self):
        """У сериала своя озвучка на каждую серию — запись должна прийти один раз."""
        voice = VoiceOver.objects.create(name="Дубляж", slug="dubbed")
        series = create_title(name="Сериал с дубляжом", type=Title.Type.SERIES)
        for number in range(1, 4):
            create_source(create_episode(series, episode=number, with_source=False), voice=voice)

        response = self.client.get(self.url, {"voice": "dubbed"})

        self.assertEqual(names(response), ["Сериал с дубляжом"])

    def test_garbage_values_do_not_break_catalog(self):
        create_title(name="Живой фильм")

        for params in [
            {"year_from": "не-год"},
            {"rating_from": "много"},
            {"quality": "'; DROP TABLE"},
            {"voice": "нет-такой"},
            {"age_rating": "99+"},
        ]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 200)

    def test_active_filter_chips_cover_new_fields(self):
        create_title(name="Фильм", quality=Title.Quality.BDRIP)

        response = self.client.get(
            self.url, {"quality": Title.Quality.BDRIP, "year_from": 2000}
        )

        fields = [item["label"] for item in response.context["active_filters"]]
        self.assertIn("BDRip", fields)
        self.assertIn("с 2000", fields)


class GenreChipTests(TestCase):
    """Чип жанра обязан сохранять уже выбранные фильтры."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_chip_keeps_other_filters(self):
        genre = create_genre(name="Драма", slug="drama")
        create_title(genres=[genre])

        response = self.client.get(
            reverse("catalog:title_list"), {"type": "movie", "sort": "-release_year"}
        )

        chips = dict((name, url) for name, url, _ in response.context["genre_chips"])
        self.assertIn("type=movie", chips["Драма"])
        self.assertIn("sort=-release_year", chips["Драма"])
        self.assertIn("genre=drama", chips["Драма"])

    def test_all_chip_clears_genre_only(self):
        genre = create_genre(name="Драма", slug="drama")
        create_title(genres=[genre])

        response = self.client.get(
            reverse("catalog:title_list"), {"genre": "drama", "type": "movie"}
        )

        chips = dict((name, url) for name, url, _ in response.context["genre_chips"])
        self.assertIn("type=movie", chips["Все"])
        self.assertNotIn("genre=", chips["Все"])


class FranchiseTests(TestCase):
    def setUp(self):
        cache.clear()
        self.franchise = Franchise.objects.create(name="Сага", slug="saga")

    def tearDown(self):
        cache.clear()

    def test_detail_lists_parts_in_release_order(self):
        create_title(name="Часть вторая", release_year=2015, franchise=self.franchise)
        create_title(name="Часть первая", release_year=2010, franchise=self.franchise)

        response = self.client.get(reverse("catalog:franchise_detail", args=["saga"]))

        self.assertEqual(names(response), ["Часть первая", "Часть вторая"])

    def test_detail_hides_drafts(self):
        create_title(name="Черновая часть", franchise=self.franchise, status=Title.Status.DRAFT)
        create_title(name="Готовая часть", franchise=self.franchise)

        response = self.client.get(reverse("catalog:franchise_detail", args=["saga"]))

        self.assertEqual(names(response), ["Готовая часть"])

    def test_title_page_shows_other_parts_without_itself(self):
        current = create_title(name="Текущая часть", release_year=2010, franchise=self.franchise)
        create_title(name="Соседняя часть", release_year=2015, franchise=self.franchise)

        response = self.client.get(current.get_absolute_url())

        parts = [title.name for title in response.context["franchise_titles"]]
        self.assertEqual(parts, ["Соседняя часть"])
        self.assertContains(response, "Все части: Сага")

    def test_title_without_franchise_has_no_block(self):
        title = create_title(name="Одиночка")

        response = self.client.get(title.get_absolute_url())

        self.assertNotIn("franchise_titles", response.context)
        self.assertNotContains(response, "Все части:")

    def test_list_hides_empty_franchises(self):
        Franchise.objects.create(name="Пустая сага", slug="empty-saga")
        create_title(name="Часть", franchise=self.franchise)

        response = self.client.get(reverse("catalog:franchise_list"))

        self.assertContains(response, "Сага")
        self.assertNotContains(response, "Пустая сага")


class SortLinkTests(TestCase):
    """Панели сортировки на главной и в каталоге питаются одним источником."""

    def setUp(self):
        cache.clear()
        create_title(name="Фильм для сортировки")

    def tearDown(self):
        cache.clear()

    def test_both_pages_use_same_shape_and_labels(self):
        home = self.client.get(reverse("catalog:home")).context["lb_sort_links"]
        catalog = self.client.get(reverse("catalog:title_list")).context["lb_sort_links"]

        self.assertEqual([label for label, _, _ in home], [label for label, _, _ in catalog])
        for label, url, is_active in home:
            self.assertIsInstance(is_active, bool)
            self.assertTrue(url.startswith("/catalog/"))

    def test_active_sort_marked_in_catalog(self):
        response = self.client.get(reverse("catalog:title_list"), {"sort": "-rating_average"})

        active = [label for label, _, is_active in response.context["lb_sort_links"] if is_active]
        self.assertEqual(active, ["По рейтингу"])


class PlaybackSourceFilterDataTests(TestCase):
    """Источники в каталоге не должны множить строки — сторож для distinct()."""

    def test_source_count_does_not_change_title_count(self):
        voice = VoiceOver.objects.create(name="Оригинал", slug="original")
        series = create_title(name="Сериал", type=Title.Type.SERIES)
        episode = create_episode(series, with_source=False)
        create_source(episode, voice=voice)
        create_source(episode, voice=voice, quality=Title.Quality.BDRIP)

        response = self.client.get(reverse("catalog:title_list"), {"voice": "original"})

        self.assertEqual(len(names(response)), 1)
        self.assertEqual(PlaybackSource.objects.count(), 2)


class RemovedAnimeTypeTests(TestCase):
    """
    Тип «Аниме» убран из каталога по решению владельца сайта.

    Проверяем не только отсутствие пункта в меню: тип раздавался ссылками
    вида ?type=anime, и они разошлись по закладкам и поисковикам. Такая
    ссылка не должна ронять страницу — только перестать что-либо отбирать.
    """

    def setUp(self):
        cache.clear()
        create_title(name="Обычный фильм")

    def tearDown(self):
        cache.clear()

    def test_type_is_not_offered_anywhere(self):
        self.assertNotIn("anime", dict(Title.Type.choices))

    def test_navigation_does_not_mention_anime(self):
        response = self.client.get(reverse("catalog:home"))

        self.assertNotContains(response, "Аниме")
        self.assertNotContains(response, "type=anime")

    def test_stale_link_opens_catalog_instead_of_failing(self):
        response = self.client.get(reverse("catalog:title_list"), {"type": "anime"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(names(response), ["Обычный фильм"])
