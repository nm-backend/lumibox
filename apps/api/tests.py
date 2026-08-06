from django.test import RequestFactory, TestCase
from django.urls import reverse
from rest_framework.throttling import AnonRateThrottle

from apps.catalog.models import Title
from apps.core.test_factories import (
    create_collection,
    create_genre,
    create_review,
    create_title,
    create_user,
)
from apps.library.models import Favorite, Watchlist
from apps.reviews.models import Review


class TitleApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.drama = create_genre(name="Драма", slug="drama")
        cls.movie = create_title(name="Публичный фильм", genres=[cls.drama])
        cls.draft = create_title(name="Секретный черновик", status=Title.Status.DRAFT)

    def test_list_returns_published_only(self):
        """Через API черновики утекли бы наружу — это проверяем в первую очередь."""
        response = self.client.get(reverse("api:v1:title-list"))
        names = [item["name"] for item in response.json()["results"]]

        self.assertIn("Публичный фильм", names)
        self.assertNotIn("Секретный черновик", names)

    def test_draft_detail_returns_404(self):
        response = self.client.get(reverse("api:v1:title-detail", args=[self.draft.slug]))
        self.assertEqual(response.status_code, 404)

    def test_detail_returns_full_payload(self):
        response = self.client.get(reverse("api:v1:title-detail", args=[self.movie.slug]))
        data = response.json()

        self.assertEqual(data["name"], "Публичный фильм")
        self.assertIn("description", data)
        self.assertIn("participations", data)

    def test_list_payload_is_lighter_than_detail(self):
        """Список из 24 карточек не должен тащить описание и съёмочную группу."""
        list_data = self.client.get(reverse("api:v1:title-list")).json()["results"][0]
        self.assertNotIn("description", list_data)
        self.assertNotIn("participations", list_data)

    def test_filter_by_genre(self):
        create_title(name="Без жанра")
        response = self.client.get(reverse("api:v1:title-list"), {"genres__slug": "drama"})
        names = [item["name"] for item in response.json()["results"]]

        self.assertEqual(names, ["Публичный фильм"])

    def test_search(self):
        response = self.client.get(reverse("api:v1:title-list"), {"search": "Публичный"})
        self.assertEqual(len(response.json()["results"]), 1)

    def test_similar_endpoint(self):
        create_title(name="Похожий", genres=[self.drama])
        response = self.client.get(reverse("api:v1:title-similar", args=[self.movie.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual([t["name"] for t in response.json()], ["Похожий"])

    def test_write_methods_rejected(self):
        """Каталог ведут через админку — API только на чтение."""
        response = self.client.post(reverse("api:v1:title-list"), {"name": "Взлом"})
        self.assertEqual(response.status_code, 405)


class FavoriteApiTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.title = create_title()
        self.url = reverse("api:v1:title-favorite", args=[self.title.slug])

    def test_guest_cannot_toggle(self):
        response = self.client.post(self.url)
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(Favorite.objects.count(), 0)

    def test_user_toggles_on_and_off(self):
        self.client.force_login(self.user)

        self.assertEqual(self.client.post(self.url).json(), {"is_favorite": True})
        self.assertEqual(self.client.post(self.url).json(), {"is_favorite": False})


class WatchlistApiTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.title = create_title()
        self.url = reverse("api:v1:title-watchlist", args=[self.title.slug])

    def test_guest_cannot_toggle(self):
        response = self.client.post(self.url)
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(Watchlist.objects.count(), 0)

    def test_user_toggles_on_and_off(self):
        self.client.force_login(self.user)

        self.assertEqual(self.client.post(self.url).json(), {"is_watchlist": True})
        self.assertEqual(self.client.post(self.url).json(), {"is_watchlist": False})


class ReviewApiTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.title = create_title()
        self.list_url = reverse("api:v1:title-reviews", args=[self.title.slug])

    def test_list_hides_moderated_reviews(self):
        create_review(title=self.title, text="Виден всем")
        create_review(title=self.title, text="Скрыт модератором", status=Review.Status.HIDDEN)

        texts = [r["text"] for r in self.client.get(self.list_url).json()["results"]]

        self.assertIn("Виден всем", texts)
        self.assertNotIn("Скрыт модератором", texts)

    def test_guest_cannot_create(self):
        response = self.client.post(self.list_url, {"rating": 8, "text": "Гость"})
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(Review.objects.count(), 0)

    def test_user_creates_review(self):
        self.client.force_login(self.user)
        response = self.client.post(self.list_url, {"rating": 9, "text": "Отлично"})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Review.objects.get(user=self.user).rating, 9)

    def test_author_and_title_come_from_server_not_client(self):
        """Иначе можно было бы оставить отзыв от чужого имени."""
        stranger = create_user()
        self.client.force_login(self.user)

        self.client.post(
            self.list_url,
            {"rating": 7, "text": "Подмена", "user": stranger.pk, "author": "Кто-то"},
        )

        review = Review.objects.get()
        self.assertEqual(review.user, self.user)
        self.assertEqual(review.title, self.title)

    def test_rating_outside_scale_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(self.list_url, {"rating": 42, "text": "x"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Review.objects.count(), 0)

    def test_second_review_rejected_with_400_not_500(self):
        """
        Ограничение уникальности не должно доходить до INSERT.

        До проверки в сериализаторе второй POST ронял сервер IntegrityError.
        """
        self.client.force_login(self.user)
        first = self.client.post(self.list_url, {"rating": 9, "text": "Раз"})
        second = self.client.post(self.list_url, {"rating": 8, "text": "Два"})

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(Review.objects.count(), 1)

    def test_author_can_still_edit_own_review(self):
        """Проверка на дубль не должна мешать править свой же отзыв."""
        review = create_review(title=self.title, user=self.user, rating=5)
        self.client.force_login(self.user)

        url = reverse("api:v1:title-review-detail", args=[self.title.slug, review.pk])
        response = self.client.patch(url, data={"rating": 9}, content_type="application/json")

        self.assertEqual(response.status_code, 200)

    def test_reviews_of_unpublished_title_are_not_exposed(self):
        """
        Редактор снял фильм с публикации — его отзывы должны исчезнуть вместе с ним.

        published() у отзыва проверяет статус отзыва, а не фильма: без отбора
        через сам Title отзывы скрытой записи продолжали отдаваться наружу.
        """
        secret = "Отзыв, который не должен пережить снятие с публикации"
        create_review(title=self.title, text=secret)
        Title.objects.filter(pk=self.title.pk).update(status=Title.Status.DRAFT)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(secret, response.content.decode())

    def test_author_can_edit_own_review(self):
        review = create_review(title=self.title, user=self.user, rating=5)
        self.client.force_login(self.user)

        url = reverse("api:v1:title-review-detail", args=[self.title.slug, review.pk])
        response = self.client.patch(
            url, data={"rating": 10}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        review.refresh_from_db()
        self.assertEqual(review.rating, 10)

    def test_stranger_cannot_edit_someone_elses_review(self):
        """Права на уровне объекта: подставить чужой номер не должно помочь."""
        review = create_review(title=self.title, user=create_user(), rating=5)
        self.client.force_login(self.user)

        url = reverse("api:v1:title-review-detail", args=[self.title.slug, review.pk])
        response = self.client.patch(
            url, data={"rating": 1}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 403)
        review.refresh_from_db()
        self.assertEqual(review.rating, 5)

    def test_stranger_cannot_delete_someone_elses_review(self):
        review = create_review(title=self.title, user=create_user())
        self.client.force_login(self.user)

        url = reverse("api:v1:title-review-detail", args=[self.title.slug, review.pk])
        response = self.client.delete(url)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Review.objects.filter(pk=review.pk).exists())


class RateTitleApiTests(TestCase):
    """Быстрая оценка звёздами с той же страницы фильма."""

    def setUp(self):
        self.user = create_user()
        self.title = create_title()
        self.url = reverse("api:v1:title-rate", args=[self.title.slug])

    def test_guest_cannot_rate(self):
        response = self.client.post(self.url, {"rating": 8}, content_type="application/json")
        self.assertIn(response.status_code, (401, 403))

    def test_quick_rating_creates_review(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"rating": 7}, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        review = Review.objects.get(user=self.user, title=self.title)
        self.assertEqual(review.rating, 7)

    def test_quick_rating_does_not_wipe_review_text(self):
        """
        Быстрая оценка меняет только оценку: текст уже оставленного
        отзыва не должен стираться (раньше update_or_create
        подставлял text='' вместе с новой оценкой).
        """
        create_review(title=self.title, user=self.user, rating=5, text="Отличное кино")
        self.client.force_login(self.user)

        response = self.client.post(self.url, {"rating": 9}, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        review = Review.objects.get(user=self.user, title=self.title)
        self.assertEqual(review.rating, 9)
        self.assertEqual(review.text, "Отличное кино")

    def test_rating_outside_scale_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"rating": 42}, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Review.objects.count(), 0)


class SchemaDocsTests(TestCase):
    """
    Документация собирается из кода. Эти тесты сторожат, что она вообще
    собирается: сломанная аннотация роняет схему целиком, а заметить это
    без теста можно только открыв страницу руками.
    """

    def test_schema_endpoint_available(self):
        response = self.client.get(reverse("api:schema"))
        self.assertEqual(response.status_code, 200)

    def test_swagger_and_redoc_available(self):
        for url_name in ("api:swagger-ui", "api:redoc"):
            with self.subTest(url_name=url_name):
                self.assertEqual(self.client.get(reverse(url_name)).status_code, 200)

    def test_schema_describes_every_endpoint(self):
        schema = self.client.get(reverse("api:schema")).content.decode()

        for path in (
            "/api/v1/titles/",
            "/api/v1/titles/{slug}/similar/",
            "/api/v1/titles/{slug}/favorite/",
            "/api/v1/titles/{title_slug}/reviews/",
            "/api/v1/collections/{slug}/titles/",
            "/api/v1/genres/",
            "/api/v1/countries/",
        ):
            with self.subTest(path=path):
                self.assertIn(path, schema)

    def test_docs_do_not_require_login(self):
        """Документация публичная: закрытая никому не нужна."""
        response = self.client.get(reverse("api:swagger-ui"))
        self.assertEqual(response.status_code, 200)


class ThrottleIdentityTests(TestCase):
    """
    Ограничение частоты — требование раздела 7 ТЗ. Ключ лимита нельзя
    брать из заголовка, который присылает сам клиент.
    """

    def test_client_cannot_reset_own_throttle_with_a_header(self):
        """
        При NUM_PROXIES=None DRF брал ключ прямо из X-Forwarded-For.
        Достаточно было менять заголовок, чтобы лимит перестал существовать.
        """
        throttle = AnonRateThrottle()
        factory = RequestFactory()

        idents = {
            throttle.get_ident(
                factory.get("/api/v1/titles/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR=spoofed)
            )
            for spoofed in ("1.1.1.1", "2.2.2.2", "3.3.3.3")
        }

        self.assertEqual(idents, {"10.0.0.1"})


class CollectionApiTests(TestCase):
    def test_unpublished_collection_hidden(self):
        create_collection(name="Видимая", is_published=True)
        create_collection(name="Скрытая", is_published=False)

        names = [c["name"] for c in self.client.get(reverse("api:v1:collection-list")).json()["results"]]

        self.assertIn("Видимая", names)
        self.assertNotIn("Скрытая", names)

    def test_collection_titles_endpoint(self):
        title = create_title(name="В подборке")
        collection = create_collection(titles=[title])

        url = reverse("api:v1:collection-titles", args=[collection.slug])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([t["name"] for t in response.json()["results"]], ["В подборке"])
