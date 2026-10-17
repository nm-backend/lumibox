"""
Тесты поиска.

Отбор живёт в одном сервисе, и его зовут три места: страница /search/,
подсказки в шапке (через API) и фильтр каталога. Поэтому основная часть
проверок бьёт по сервису, а остальные — по тому, что все три места
находят одно и то же.
"""

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.catalog.models import Participation, Studio, Title
from apps.catalog.services import search_persons, search_titles
from apps.core.test_factories import (
    create_country,
    create_genre,
    create_participation,
    create_person,
    create_title,
)
from apps.core.text import MAX_QUERY_LENGTH, clean_query


class SearchTitlesServiceTests(TestCase):
    def test_finds_by_name_and_original_name(self):
        create_title(name="Начало", original_name="Inception")

        self.assertEqual(search_titles("Нач").count(), 1)
        self.assertEqual(search_titles("incep").count(), 1)

    def test_finds_by_description(self):
        create_title(name="Безымянный", description="История про космический лифт.")

        self.assertEqual(search_titles("космическ").count(), 1)

    def test_finds_by_genre_country_and_studio(self):
        studio = Studio.objects.create(name="Мосфильм", slug="mosfilm")
        title = create_title(
            name="Без подсказок",
            description="",
            genres=[create_genre(name="Комедия", slug="comedy")],
            countries=[create_country(name="Япония", slug="japan")],
        )
        title.studios.add(studio)

        for query in ["Комеди", "Япони", "Мосфильм"]:
            with self.subTest(query=query):
                self.assertEqual(search_titles(query).count(), 1)

    def test_does_not_duplicate_on_several_matching_genres(self):
        """Две подходящие связи не должны давать две строки."""
        create_title(
            name="Драма и мелодрама",
            genres=[
                create_genre(name="Драма", slug="drama"),
                create_genre(name="Драматургия", slug="dramaturgy"),
            ],
        )

        self.assertEqual(search_titles("Драм").count(), 1)

    def test_hides_drafts(self):
        create_title(name="Секретный черновик", status=Title.Status.DRAFT)

        self.assertEqual(search_titles("Секретный").count(), 0)

    def test_short_and_empty_queries_return_nothing(self):
        """Показывать весь каталог в ответ на один символ — обманывать."""
        create_title(name="Любой фильм")

        for query in ["", "  ", "а", None]:
            with self.subTest(query=query):
                self.assertEqual(search_titles(query).count(), 0)

    def test_limit_applied(self):
        for number in range(5):
            create_title(name=f"Похожее название {number}")

        self.assertEqual(len(search_titles("Похожее", limit=2)), 2)


class SearchPersonsServiceTests(TestCase):
    def test_finds_person_with_published_work(self):
        person = create_person(name="Пётр Актёров")
        create_participation(title=create_title(), person=person)

        self.assertEqual(search_persons("Актёров").count(), 1)

    def test_hides_person_without_published_work(self):
        person = create_person(name="Призрачный актёр")
        create_participation(
            title=create_title(status=Title.Status.DRAFT), person=person
        )

        self.assertEqual(search_persons("Призрачный").count(), 0)

    def test_finds_by_original_name(self):
        """ActorSearchView искал только по name, хотя оригинал показывал."""
        person = create_person(name="Киану Ривз", original_name="Keanu Reeves")
        create_participation(title=create_title(), person=person)

        self.assertEqual(search_persons("keanu").count(), 1)


class SearchPageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse("catalog:search")

    def tearDown(self):
        cache.clear()

    def test_page_opens_without_query(self):
        """
        Страница поиска без запроса объясняет, что тут можно найти.

        Раньше это была служебная строка «Введите запрос — найдём фильмы,
        сериалы и людей» тем же классом, что и счётчик результатов. Теперь
        это обычное пустое состояние, как на остальных страницах сайта,
        поэтому проверяем его, а не конкретную формулировку.
        """
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "empty-state")
        self.assertContains(response, "Что ищем?")

    def test_short_query_explains_itself(self):
        response = self.client.get(self.url, {"q": "а"})

        self.assertTrue(response.context["too_short"])
        self.assertContains(response, "хотя бы два символа")

    def test_finds_titles_and_persons(self):
        create_title(name="Матрица")
        person = create_person(name="Матрёна Иванова")
        create_participation(title=create_title(name="Другой"), person=person)

        response = self.client.get(self.url, {"q": "Матр"})

        self.assertContains(response, "Матрица")
        self.assertContains(response, "Матрёна Иванова")

    def test_empty_result_offers_catalog(self):
        create_title(name="Что-то")

        response = self.client.get(self.url, {"q": "нетакогослова"})

        self.assertContains(response, "Открыть весь каталог")

    def test_results_are_paginated(self):
        for number in range(30):
            create_title(name=f"Серийное название {number}")

        response = self.client.get(self.url, {"q": "Серийное"})

        self.assertEqual(response.context["paginator"].count, 30)
        self.assertEqual(len(response.context["titles"]), 24)

    def test_page_is_not_indexed(self):
        """Запросов бесконечно много — каждый дал бы почти пустой адрес."""
        response = self.client.get(self.url, {"q": "что-нибудь"})

        self.assertContains(response, 'content="noindex, follow"')

    def test_header_form_points_to_search_page(self):
        response = self.client.get(reverse("catalog:home"))

        self.assertContains(response, f'action="{self.url}"')

    def test_query_count_does_not_grow_with_results(self):
        """
        Выдача рисуется той же карточкой, что и каталог, и требует тех же
        префетчей. Без них страница добирала жанры, страны и прогресс
        по одному на запись: тридцать результатов стоили под сотню
        запросов, и это росло линейно вместе с каталогом.

        Сравниваем два размера выдачи, а не фиксируем магическое число:
        точное количество запросов зависит от блоков сайдбара и меняется
        при их правке, а вот расти от числа найденных записей оно
        не должно.
        """
        self._fill(3)
        few = self._measure()

        self._fill(15)
        many = self._measure()

        self.assertEqual(len(few), len(many))

    def _measure(self):
        """
        Считает запросы одной страницы выдачи на прогретом кэше.

        Прогрев обязателен перед каждым замером: добавление записей шлёт
        сигналы, те сбрасывают кэш сайдбара, и холодный запрос стоит
        дороже горячего. Без прогрева мы сравнивали бы состояние кэша,
        а не количество результатов.
        """
        self.client.get(self.url, {"q": "Космос"})
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(self.url, {"q": "Космос"})
        return ctx

    def _fill(self, count):
        genre, country = create_genre(), create_country()
        for number in range(count):
            create_title(
                name=f"Космос {number}",
                genres=[genre],
                countries=[country],
                description="Фильм про космос",
            )


class SearchSuggestApiTests(TestCase):
    def setUp(self):
        self.url = reverse("api:v1:title-search")

    def test_type_label_comes_from_server(self):
        """
        Скрипт подписывал «Сериалом» всё, что не «movie», — включая
        мультфильмы и ТВ-шоу.
        """
        create_title(name="Мультик про кота", type=Title.Type.CARTOON)

        payload = self.client.get(self.url, {"q": "Мультик"}).json()

        self.assertEqual(payload[0]["type"], "cartoon")
        self.assertEqual(payload[0]["type_display"], "Мультфильм")

    def test_suggestions_use_same_scope_as_page(self):
        """Подсказки и страница должны находить одно и то же."""
        create_title(name="Без совпадения в названии", description="Про подводную лодку")

        payload = self.client.get(self.url, {"q": "подводную"}).json()

        self.assertEqual(len(payload), 1)

    def test_persons_included_and_labelled(self):
        person = create_person(name="Иван Режиссёров")
        create_participation(
            title=create_title(), person=person, role=Participation.Role.DIRECTOR
        )

        payload = self.client.get(self.url, {"q": "Режиссёров"}).json()

        kinds = {item["type"] for item in payload}
        self.assertIn("person", kinds)

    def test_short_query_returns_nothing(self):
        create_title(name="Абракадабра")

        self.assertEqual(self.client.get(self.url, {"q": "а"}).json(), [])

    def test_limit_is_respected(self):
        for number in range(10):
            create_title(name=f"Одинаковое название {number}")

        payload = self.client.get(self.url, {"q": "Одинаковое", "limit": 3}).json()

        self.assertEqual(len(payload), 3)


class ControlCharacterTests(TestCase):
    """
    Управляющие символы в поисковой строке не должны доходить до базы.

    PostgreSQL отказывается принимать NUL (0x00) в параметрах запроса:
    драйвер поднимает ValueError, и страница отвечает 500. SQLite такую
    строку пропускает, поэтому локальный прогон дефект не ловил — его
    поймал CI на PostgreSQL. Здесь проверяется само требование (в SQL
    не уходит управляющих символов), а не поведение конкретной СУБД,
    так что падение воспроизводится и на SQLite.
    """

    PAYLOAD = "\x00\x01\x02"

    def setUp(self):
        create_title(name="Начало", original_name="Inception")

    def _params_without_control(self, callback):
        """Выполняет запрос и возвращает все параметры SQL для проверки."""
        captured = []

        def wrapper(execute, sql, params, many, context):
            captured.append(params)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(wrapper):
            response = callback()

        flat = " ".join(str(part) for params in captured for part in (params or ()))
        return response, flat

    def test_clean_query_strips_control_characters(self):
        self.assertEqual(clean_query("\x00\x01Начало\x02"), "Начало")
        self.assertEqual(clean_query("На\u200bчало"), "Начало")  # мягкий перенос
        self.assertEqual(clean_query(None), "")
        self.assertEqual(clean_query("   "), "")
        # Запрос длиннее лимита обрезается, а не отвергается.
        self.assertEqual(len(clean_query("ы" * 500)), MAX_QUERY_LENGTH)

    def test_search_page_never_sends_control_characters_to_sql(self):
        response, params = self._params_without_control(
            lambda: self.client.get(reverse("catalog:search"), {"q": self.PAYLOAD})
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("\x00", params)

    def test_cleaning_does_not_break_a_real_query(self):
        """Мусор рядом со словом не должен отменять сам поиск."""
        queryset = search_titles("Начало\x00\x01")

        self.assertEqual(queryset.count(), 1)

    def test_catalog_filter_never_sends_control_characters_to_sql(self):
        response, params = self._params_without_control(
            lambda: self.client.get(reverse("catalog:title_list"), {"q": self.PAYLOAD})
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("\x00", params)

    def test_actor_search_never_sends_control_characters_to_sql(self):
        for extra in ({}, {"json": "1"}):
            with self.subTest(json=bool(extra)):
                response, params = self._params_without_control(
                    lambda: self.client.get(
                        reverse("catalog:actor_search"),
                        {"q": self.PAYLOAD, **extra},
                        headers={"X-Requested-With": "XMLHttpRequest"} if extra else {},
                    )
                )

                self.assertEqual(response.status_code, 200)
                self.assertNotIn("\x00", params)

    def test_api_search_never_sends_control_characters_to_sql(self):
        response, params = self._params_without_control(
            lambda: self.client.get("/api/v1/titles/search/", {"q": self.PAYLOAD})
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("\x00", params)

    def test_api_search_filter_never_sends_control_characters_to_sql(self):
        """
        У списка записей поиск идёт через DRF SearchFilter (?search=).

        У него своя проверка значения (CharField отказывается от NUL), но
        до неё дело доходит только если NUL уцелел в строке запроса —
        этим занимается middleware, и здесь проверяется результат.
        """
        response, params = self._params_without_control(
            lambda: self.client.get("/api/v1/titles/", {"search": self.PAYLOAD})
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("\x00", params)
