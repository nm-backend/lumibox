"""Все сообщения об ошибках для человека — на русском.

Сайт по умолчанию русский, но у Django и DRF есть служебные английские
фразы, которые никто не переводит:

* get_object_or_404 и get_object() поднимают Http404 с текстом
  «No Title matches the given query.» — и он уходил в detail ответа API;
* отказ проверки CSRF рисует служебную страницу Django: серое оформление
  фреймворка, <html lang="en"> на русском тексте и совет посетителю
  «включить отладочный режим, установив значение DEBUG=True»;
* DRF отвечает «CSRF Failed: CSRF cookie not set.»;
* проверки полей без перевода дают «This field is required», «Enter a valid…».

Ни одну из этих строк посетитель видеть не должен: человек читает объяснение
на русском, а не обрывок внутреннего устройства. Тест прогоняет тот же мусор,
что и остальные аудиторские модули, и проверяет каждый показанный текст:
сообщение обязано содержать кириллицу. Латинские имена внутри русской фразы
(имя файла, слаг) допустимы — важно, что сама фраза русская.
"""

import json
import re
from io import BytesIO

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from apps.api.v1.exceptions import CSRF_DETAIL
from apps.core.test_factories import create_title, create_user
from apps.reviews.models import Comment, Review

CYRILLIC = re.compile("[А-Яа-яЁё]")

# Разметка ошибок: <p class="form__error"> у поля и блок form__errors
# с ошибками формы целиком. Класс один на весь проект (includes/form_fields.html).
ERROR_PARAGRAPH = re.compile(r'<p class="form__error"[^>]*>(.*?)</p>', re.S)
ERROR_BOX = re.compile(r'<div class="form__errors"[^>]*>(.*?)</div>', re.S)
INNER_PARAGRAPH = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
ANY_TAG = re.compile(r"<[^>]+>")

# Английские заглушки фреймворков. Ни одна не должна попасть в ответ.
ENGLISH_FALLBACKS = (
    "matches the given query",
    "CSRF Failed",
    "CSRF verification failed",
    "More information is available with DEBUG=True",
    "This field is required",
    "Enter a valid",
    "Ensure this value",
    "Upload a valid image",
    "Invalid page",
    "Page not found",
    "Not Found",
    "Bad Request",
    "Method Not Allowed",
    "Server Error",
    "Traceback (most recent call last)",
    "Django Version",
)


class MessageLanguageMixin:
    """Сбор показанных сообщений и проверка, что они русские.

    Метка аудита — по ней набор выделяется в отдельный шаг CI. Живёт на
    общем предке, поэтому под неё попадает и любой новый тест модуля.
    """

    tags = ("adversarial",)

    def setUp(self):
        cache.clear()
        super().setUp()
        # raise_request_exception=False: падение должно вернуться страницей,
        # которую увидит человек, а не ошибкой в тесте.
        self.client = Client(raise_request_exception=False)

    def messages(self, response):
        """Тексты ошибок из ответа: из формы, из блока ошибок и из JSON."""
        body = response.content.decode("utf-8", errors="replace")
        texts = list(ERROR_PARAGRAPH.findall(body))
        for box in ERROR_BOX.findall(body):
            texts.extend(INNER_PARAGRAPH.findall(box))

        if response.status_code >= 400 and "json" in response.get("Content-Type", ""):
            try:
                texts.extend(self._strings(response.json()))
            except ValueError:  # pragma: no cover — неразбираемый JSON
                pass

        return [" ".join(ANY_TAG.sub(" ", text).split()) for text in texts if text.strip()]

    def _strings(self, node):
        """Все строки внутри JSON-ответа — сообщения об ошибке живут там."""
        if isinstance(node, str):
            return [node]
        if isinstance(node, list):
            return [text for item in node for text in self._strings(item)]
        if isinstance(node, dict):
            return [text for value in node.values() for text in self._strings(value)]
        return []

    def assert_messages_russian(self, response, label, expect_messages=True):
        found = self.messages(response)
        if expect_messages:
            self.assertTrue(found, f"{label}: ошибки показаны, но сообщений нет — тест ничего не проверил")
        for text in found:
            self.assertRegex(text, CYRILLIC, f"{label}: сообщение без русского текста: {text!r}")

        body = response.content.decode("utf-8", errors="replace")
        for marker in ENGLISH_FALLBACKS:
            self.assertNotIn(marker, body, f"{label}: английская заглушка {marker!r}")


class FormMessageLanguageTests(MessageLanguageMixin, TestCase):
    """Формы сайта: мусор на входе — русский текст на выходе."""

    def setUp(self):
        super().setUp()
        self.user = create_user()
        self.title = create_title()

    def test_login_and_register(self):
        cases = (
            ("вход: мусор в почте", "/login/", {"username": "не-почта", "password": "x"}),
            ("вход: пустая форма", "/login/", {}),
            ("регистрация: пустая форма", "/register/", {}),
            (
                "регистрация: слабый пароль",
                "/register/",
                {"email": "a@example.com", "username": "newuser", "password1": "12345678", "password2": "12345678"},
            ),
            (
                "регистрация: занятая почта",
                "/register/",
                {
                    "email": self.user.email,
                    "username": "someone_else",
                    "password1": "Strong-Pass-2026!",
                    "password2": "Strong-Pass-2026!",
                },
            ),
            ("сброс пароля: мусор", "/password-reset/", {"email": "\x00ы"}),
        )
        for label, url, data in cases:
            with self.subTest(label=label):
                self.assert_messages_russian(self.client.post(url, data), label)

    def test_profile_and_content_forms(self):
        self.client.force_login(self.user)
        cases = (
            ("профиль: мусорное имя", "/profile/", {"username": "###", "bio": ""}),
            ("профиль: длинное био", "/profile/", {"username": self.user.username, "bio": "ы" * 50_000}),
            ("отзыв: оценка 999", f"/title/{self.title.slug}/review/", {"rating": "999", "text": "ок"}),
            ("отзыв: пустая форма", f"/title/{self.title.slug}/review/", {"rating": "", "text": ""}),
            ("комментарий: пустой", f"/title/{self.title.slug}/comment/", {"text": "", "parent": ""}),
            ("комментарий: длинный", f"/title/{self.title.slug}/comment/", {"text": "ы" * 5000, "parent": ""}),
        )
        for label, url, data in cases:
            with self.subTest(label=label):
                self.assert_messages_russian(self.client.post(url, data), label)

    def test_avatar_garbage(self):
        self.client.force_login(self.user)
        avatar = SimpleUploadedFile(
            "../../не-картинка.jpg",
            "это не изображение".encode(),
            content_type="image/jpeg",
        )
        response = self.client.post(
            "/profile/",
            {"username": self.user.username, "bio": "", "avatar": avatar},
        )
        self.assert_messages_russian(response, "профиль: не-картинка в аватаре")

    def test_broken_image_avatar(self):
        self.client.force_login(self.user)
        buffer = BytesIO()
        buffer.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
        avatar = SimpleUploadedFile("avatar.png", buffer.getvalue(), content_type="image/png")
        response = self.client.post(
            "/profile/",
            {"username": self.user.username, "bio": "", "avatar": avatar},
        )
        self.assert_messages_russian(response, "профиль: битый PNG")

    def test_form_pages_have_no_english(self):
        for url in ("/login/", "/register/", "/password-reset/", "/profile/", "/search/"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assert_messages_russian(response, url, expect_messages=False)


class ApiMessageLanguageTests(MessageLanguageMixin, TestCase):
    """API: отказ должен быть понятен, а не «No Title matches the given query.»"""

    def setUp(self):
        super().setUp()
        self.user = create_user()
        self.title = create_title()
        self.client.force_login(self.user)

    def test_validation_messages(self):
        comments_url = f"/api/v1/titles/{self.title.slug}/comments/"
        cases = (
            ("rate: строка", f"/api/v1/titles/{self.title.slug}/rate/", {"rating": "abc"}),
            ("rate: ноль", f"/api/v1/titles/{self.title.slug}/rate/", {"rating": 0}),
            ("watch: строка", f"/api/v1/titles/{self.title.slug}/watch/", {"position": "abc"}),
            ("comments: parent строка", comments_url, {"text": "привет", "parent": "abc"}),
            ("comments: parent за границей", comments_url, {"text": "привет", "parent": 2**63}),
            ("comments: NUL", comments_url, {"text": "а\u0000б"}),
            ("comments: пустой текст", comments_url, {"text": ""}),
            # Отзыв без текста API принимает осознанно: оценку можно
            # поставить одной кнопкой. Мусор здесь — текст сверх лимита.
            (
                "reviews: длинный текст",
                f"/api/v1/titles/{self.title.slug}/reviews/",
                {"rating": 8, "text": "ы" * 5000},
            ),
        )
        for label, url, payload in cases:
            with self.subTest(label=label):
                response = self.client.post(url, data=json.dumps(payload), content_type="application/json")
                self.assertGreaterEqual(response.status_code, 400, label)
                self.assert_messages_russian(response, label)

    def test_not_found_does_not_leak_model_name(self):
        # Слаги латиницей, как их шлёт настоящий клиент: конвертер Django
        # принимает только [-a-zA-Z0-9_], а у вложенных адресов API свой
        # шаблон пути и адрес с кириллицей до вьюхи просто не дойдёт.
        for url in (
            "/api/v1/titles/no-such-title-9999/",
            "/api/v1/genres/no-such-genre-9999/",
            "/api/v1/countries/no-such-country-9999/",
            "/api/v1/collections/no-such-collection-9999/",
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404, url)
                self.assert_messages_russian(response, url)
                body = response.content.decode("utf-8", errors="replace")
                for model_name in ("Title", "Genre", "Country", "Collection"):
                    self.assertNotIn(model_name, body, f"{url}: в ответе имя модели {model_name}")

    def test_not_found_messages_for_written_endpoints(self):
        for url in ("/api/v1/titles/no-such-title-9999/comments/", "/api/v1/titles/no-such-title-9999/rate/"):
            with self.subTest(url=url):
                response = self.client.get(url) if url.endswith("comments/") else self.client.post(
                    url, data="{}", content_type="application/json"
                )
                self.assertEqual(response.status_code, 404, url)
                self.assert_messages_russian(response, url)

    def test_garbage_query_parameters(self):
        cases = (
            ("API: мусорный page", {"page": "abc", "page_size": "1e999"}),
            ("API: мусорный фильтр", {"release_year": "abc", "ordering": "\x00"}),
            ("API: page за границей", {"page": 2**63}),
        )
        for label, params in cases:
            with self.subTest(label=label):
                response = self.client.get("/api/v1/titles/", params)
                self.assert_messages_russian(response, label, expect_messages=response.status_code >= 400)

    def test_from_english_client_answers_in_russian(self):
        """Язык ответа не должен зависеть от заголовка Accept-Language."""
        response = self.client.post(
            f"/api/v1/titles/{self.title.slug}/rate/",
            data=json.dumps({"rating": 99}),
            content_type="application/json",
            HTTP_ACCEPT_LANGUAGE="en-US,en;q=0.9",
        )
        self.assertGreaterEqual(response.status_code, 400)
        self.assert_messages_russian(response, "rate: английский клиент")

    def test_garbage_is_never_saved(self):
        """Мусор отсекается: ни комментария с NUL, ни отзыва сверх лимита."""
        self.client.post(
            f"/api/v1/titles/{self.title.slug}/comments/",
            data=json.dumps({"text": "а\u0000б"}),
            content_type="application/json",
        )
        self.assertEqual(Comment.objects.filter(title=self.title).count(), 0)
        self.client.post(
            f"/api/v1/titles/{self.title.slug}/reviews/",
            data=json.dumps({"rating": 8, "text": "ы" * 5000}),
            content_type="application/json",
        )
        self.assertEqual(Review.objects.filter(title=self.title).count(), 0)


class ErrorPageLanguageTests(MessageLanguageMixin, TestCase):
    """Страницы ошибок и отказ CSRF — на русском, без служебных подсказок."""

    def test_404_page_is_russian(self):
        response = self.client.get("/такой-страницы-нет-9999/")
        self.assertEqual(response.status_code, 404)
        self.assert_messages_russian(response, "404", expect_messages=False)
        body = response.content.decode("utf-8", errors="replace")
        self.assertIn("Страница не найдена", body)

    def test_nul_and_garbage_in_path_are_russian(self):
        for url in ("/catalog/%00/", "/catalog/" + "ы" * 300 + "/", "/title/%2e%2e%2f%2e%2e/"):
            with self.subTest(url=url[:40]):
                response = self.client.get(url)
                self.assert_messages_russian(response, f"путь {url[:40]}", expect_messages=False)

    def test_csrf_failure_page_is_russian(self):
        """Просроченный токен в форме: человек должен увидеть нашу страницу.

        Без шаблона 403_csrf.html Django рисует свою: серое оформление
        фреймворка, <html lang="en"> на русском тексте и совет включить
        DEBUG=True — то есть посетитель читал служебную страницу вместо
        объяснения.
        """
        client = Client(enforce_csrf_checks=True, raise_request_exception=False)
        client.force_login(create_user())
        title = create_title()

        for label, url, data in (
            ("отзыв", f"/title/{title.slug}/review/", {"rating": "8", "text": "ок"}),
            ("профиль", "/profile/", {"username": "someone", "bio": ""}),
            ("комментарий", f"/title/{title.slug}/comment/", {"text": "ок", "parent": ""}),
        ):
            with self.subTest(label=label):
                response = client.post(url, data)
                self.assertEqual(response.status_code, 403, label)
                self.assert_messages_russian(response, f"CSRF: {label}", expect_messages=False)
                body = response.content.decode("utf-8", errors="replace")
                self.assertNotIn("<html lang=\"en\"", body, f"CSRF: {label}: служебная страница Django")
                self.assertIn("Форма устарела", body, f"CSRF: {label}: нет нашей страницы")

    def test_api_csrf_failure_is_russian(self):
        client = Client(enforce_csrf_checks=True, raise_request_exception=False)
        client.force_login(create_user())
        title = create_title()
        response = client.post(
            f"/api/v1/titles/{title.slug}/rate/",
            data=json.dumps({"rating": 8}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assert_messages_russian(response, "API: CSRF")
        # Текст наш, а не DRF-овский «CSRF Failed: CSRF cookie not set.»
        self.assertEqual(response.json()["detail"], CSRF_DETAIL)
