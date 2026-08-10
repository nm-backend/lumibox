"""
Тесты поиска.

Отбор живёт в одном сервисе, и его зовут три места: страница /search/,
подсказки в шапке (через API) и фильтр каталога. Поэтому основная часть
проверок бьёт по сервису, а остальные — по тому, что все три места
находят одно и то же.
"""

from django.core.cache import cache
from django.test import TestCase
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
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Введите запрос")

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


class SearchSuggestApiTests(TestCase):
    def setUp(self):
        self.url = reverse("api:v1:title-search")

    def test_type_label_comes_from_server(self):
        """
        Скрипт подписывал «Сериалом» всё, что не «movie», — включая
        мультфильмы, ТВ-шоу и аниме.
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
