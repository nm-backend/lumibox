"""
Полный путь фильма от админки до сайта — раздел 12 требований.

Каждый кусок этой цепочки уже покрыт отдельными тестами. Здесь проверяется
именно связка: редактор нажал «Сохранить» в админке — и запись появилась
везде, включая кэшированную главную. Ломается обычно как раз стык,
а не отдельное звено.
"""

import io

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from apps.catalog.models import Collection, CollectionItem, Country, Genre, Participation, Person, Title
from apps.core.test_factories import create_review, create_user

User = get_user_model()


def make_poster():
    buffer = io.BytesIO()
    Image.new("RGB", (300, 450), "navy").save(buffer, "JPEG")
    return SimpleUploadedFile("poster.jpg", buffer.getvalue(), content_type="image/jpeg")


class PublicationFlowTests(TestCase):
    """Редактор публикует фильм — проверяем, что он дошёл до всех витрин."""

    @classmethod
    def setUpTestData(cls):
        cls.editor = User.objects.create_superuser(
            email="editor@example.com", username="editor", password="editor-Пароль-77"
        )
        cls.drama = Genre.objects.create(name="Драма", slug="flow-drama")
        cls.usa = Country.objects.create(name="США", slug="flow-usa")
        cls.director = Person.objects.create(name="Режиссёр Тестов", slug="flow-director")
        cls.actor = Person.objects.create(name="Актёр Тестов", slug="flow-actor")

    def setUp(self):
        cache.clear()
        self.client.force_login(self.editor)

    def tearDown(self):
        cache.clear()

    def publish_via_admin(self, **overrides):
        """Создаёт фильм ровно так, как это делает редактор через форму админки."""
        data = {
            "type": Title.Type.MOVIE,
            "name": "Полный Цикл",
            "original_name": "Full Cycle",
            "slug": "polnyy-cikl",
            "description": "Фильм, созданный через админку для проверки всей цепочки.",
            "release_year": 2024,
            "duration_minutes": 120,
            "age_rating": "16+",
            "trailer_url": "https://www.youtube.com/watch?v=test",
            "genres": [self.drama.pk],
            "countries": [self.usa.pk],
            "status": Title.Status.PUBLISHED,
            "meta_title": "",
            "meta_description": "",
            "published_at": "",
            # Инлайны требуют management-форму — по одной на каждый.
            # Без блока frames-* Django отвергнет весь POST целиком.
            "participations-TOTAL_FORMS": "2",
            "participations-INITIAL_FORMS": "0",
            "participations-MIN_NUM_FORMS": "0",
            "participations-MAX_NUM_FORMS": "1000",
            "frames-TOTAL_FORMS": "0",
            "frames-INITIAL_FORMS": "0",
            "frames-MIN_NUM_FORMS": "0",
            "frames-MAX_NUM_FORMS": "1000",
            "participations-0-person": self.director.pk,
            "participations-0-role": Participation.Role.DIRECTOR,
            "participations-0-character": "",
            "participations-0-order": "1",
            "participations-1-person": self.actor.pk,
            "participations-1-role": Participation.Role.ACTOR,
            "participations-1-character": "Главный герой",
            "participations-1-order": "2",
        }
        data.update(overrides)
        return self.client.post(
            reverse("admin:catalog_title_add"),
            data={**data, "poster": make_poster()},
            follow=True,
        )

    def test_full_cycle_from_admin_to_every_surface(self):
        response = self.publish_via_admin()
        self.assertEqual(response.status_code, 200)

        title = Title.objects.filter(slug="polnyy-cikl").first()
        self.assertIsNotNone(title, "Фильм не создался — форма админки отвергла данные")

        with self.subTest("сохранились все поля"):
            self.assertEqual(title.status, Title.Status.PUBLISHED)
            self.assertIsNotNone(title.published_at, "дата публикации должна проставиться сама")
            self.assertTrue(title.poster, "постер не загрузился")
            self.assertEqual(title.age_rating, "16+")
            self.assertEqual(list(title.genres.all()), [self.drama])
            self.assertEqual(list(title.countries.all()), [self.usa])
            self.assertEqual(title.participations.count(), 2)

        with self.subTest("страница фильма открывается"):
            page = self.client.get(title.get_absolute_url())
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, "Полный Цикл")
            self.assertContains(page, "Режиссёр Тестов")
            self.assertContains(page, "Главный герой")
            # Сторож против утечки комментария: многострочный {# #} Django
            # не считает комментарием и печатает в HTML. Этот фрагмент лежит
            # в блоке трейлера, который здесь как раз отрисован.
            self.assertNotContains(page, "Модальное окно")

        with self.subTest("виден в каталоге"):
            self.assertContains(self.client.get(reverse("catalog:title_list")), "Полный Цикл")

        with self.subTest("находится поиском"):
            found = self.client.get(reverse("catalog:title_list"), {"q": "Полный"})
            self.assertContains(found, "Полный Цикл")

        with self.subTest("находится по оригинальному названию"):
            found = self.client.get(reverse("catalog:title_list"), {"q": "Full Cycle"})
            self.assertContains(found, "Полный Цикл")

        with self.subTest("виден на главной, кэш сбросился"):
            # Главная кэшируется на пять минут. Если сигнал не сбросил кэш,
            # редактор решит, что публикация не сработала.
            self.assertContains(self.client.get(reverse("catalog:home")), "Полный Цикл")

        with self.subTest("виден на странице жанра и страны"):
            self.assertContains(
                self.client.get(reverse("catalog:genre_titles", args=[self.drama.slug])), "Полный Цикл"
            )
            self.assertContains(
                self.client.get(reverse("catalog:country_titles", args=[self.usa.slug])), "Полный Цикл"
            )

        with self.subTest("виден на странице персоны"):
            self.assertContains(
                self.client.get(self.director.get_absolute_url()), "Полный Цикл"
            )

        with self.subTest("отдаётся через API"):
            api = self.client.get(reverse("api:v1:title-detail", args=[title.slug]))
            self.assertEqual(api.status_code, 200)
            payload = api.json()
            self.assertEqual(payload["name"], "Полный Цикл")
            self.assertEqual(len(payload["participations"]), 2)

        with self.subTest("работают отзывы и рейтинг"):
            create_review(title=title, user=create_user(), rating=9)
            title.refresh_from_db()
            self.assertEqual(float(title.rating_average), 9.0)
            self.assertContains(self.client.get(title.get_absolute_url()), "9")

        with self.subTest("работают рекомендации"):
            neighbour = Title.objects.create(
                name="Сосед по жанру", slug="sosed", release_year=2023, status=Title.Status.PUBLISHED
            )
            neighbour.genres.set([self.drama])
            self.assertContains(self.client.get(title.get_absolute_url()), "Сосед по жанру")

        with self.subTest("попадает в подборку"):
            collection = Collection.objects.create(
                name="Тестовая подборка", slug="flow-collection", is_published=True
            )
            CollectionItem.objects.create(collection=collection, title=title, order=1)
            self.assertContains(self.client.get(collection.get_absolute_url()), "Полный Цикл")

    def test_draft_created_in_admin_stays_invisible(self):
        """Обратная сторона: черновик не должен утечь никуда."""
        self.publish_via_admin(
            name="Тайный Черновик", slug="taynyy-chernovik", status=Title.Status.DRAFT
        )

        draft = Title.objects.get(slug="taynyy-chernovik")
        self.assertIsNone(draft.published_at)

        anonymous = self.client_class(headers={"host": "testserver"})
        for url in (
            reverse("catalog:home"),
            reverse("catalog:title_list"),
            reverse("catalog:title_list") + "?q=Тайный",
            reverse("api:v1:title-list"),
        ):
            with self.subTest(url=url):
                self.assertNotContains(anonymous.get(url), "Тайный Черновик")

        self.assertEqual(anonymous.get(draft.get_absolute_url()).status_code, 404)

    def test_unpublishing_removes_title_from_site(self):
        """Снятие с публикации должно убирать запись отовсюду, включая главную."""
        self.publish_via_admin()
        title = Title.objects.get(slug="polnyy-cikl")

        self.assertContains(self.client.get(reverse("catalog:home")), "Полный Цикл")

        # Массовое действие админки — тот путь, которым пользуется редактор.
        self.client.post(
            reverse("admin:catalog_title_changelist"),
            {"action": "unpublish", "_selected_action": [title.pk]},
            follow=True,
        )

        title.refresh_from_db()
        self.assertEqual(title.status, Title.Status.DRAFT)
        self.assertNotContains(self.client.get(reverse("catalog:home")), "Полный Цикл")
        self.assertEqual(self.client.get(title.get_absolute_url()).status_code, 404)
