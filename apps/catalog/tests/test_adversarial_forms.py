"""Adversarial tests for every user-facing form and button.

Attack surface: garbage typed by a human — wrong format, huge values,
control characters, tampered hidden inputs, hostile ?next= targets — plus
malformed request bodies.

Two properties are checked for each form:

* the site does not break: no 500, no unhandled exception;
* the visitor is not shown raw system text: no traceback, no Python or
  framework error names, no untranslated English validation fallbacks.

The only database the CI guarantees is PostgreSQL, local runs use SQLite;
the tests below stay engine-neutral. NUL bytes, which PostgreSQL refuses
outright, are asserted at the application layer: whatever reaches the
database must not contain them.
"""

import json
from io import BytesIO

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from PIL import Image

from apps.core.test_factories import create_title, create_user
from apps.reviews.models import Comment, Review

# Never allowed in a response, whatever the input: traceback markers,
# exception names, Django service pages, English validation fallbacks.
SYSTEM_MARKERS = (
    "Traceback (most recent call last)",
    "Exception Value",
    "Exception Type",
    "Request Method:",
    "Django Version",
    "Python Version",
    "Python Executable",
    "Settings module",
    "django.core.exceptions",
    "TemplateDoesNotExist",
    "ImproperlyConfigured",
    "OperationalError",
    "ProgrammingError",
    "IntegrityError",
    "DataError",
    "psycopg",
    "Server Error (500)",
    "This field is required",
    "Enter a valid",
    "Ensure this value",
    "Upload a valid image",
)


def _body(response):
    return response.content.decode("utf-8", errors="replace")


class GarbageFormMixin:
    """Shared client and assertions for garbage-input tests.

    Метка аудита: по ней набор выделяется в отдельный шаг CI — он заметно
    медленнее остальных (каждая форма прогоняется десятками мусорных
    значений) и полезен сам по себе, а не только как часть всего прогона.
    Метка живёт на общем предке, поэтому под неё попадает любой новый тест
    из этого модуля, даже если про метку забыли.
    """

    tags = ("adversarial",)

    def setUp(self):
        cache.clear()
        super().setUp()
        # raise_request_exception=False: a crash must come back as the
        # custom 500 page the visitor would see, not as a test error.
        self.client = Client(raise_request_exception=False)

    def assert_survived(self, response, label):
        self.assertNotEqual(response.status_code, 500, f"{label}: ответ 500 (страница падения)")
        self.assert_no_system_text(response, label)

    def assert_no_system_text(self, response, label):
        body = _body(response)
        for marker in SYSTEM_MARKERS:
            self.assertNotIn(marker, body, f"{label}: в ответе системный текст {marker!r}")

    def assert_readable_errors(self, response, label):
        """The page must render human-readable validation feedback."""
        body = _body(response)
        self.assertIn("form__error", body, f"{label}: ошибки формы не показаны человеку")


PAYLOADS = (
    "ы" * 10_000,
    "<script>alert(1)</script>",
    "'; DROP TABLE catalog_title; --",
    "\x00\x01\x02",
    "🔥ёй漢字\u202e",
    "   ",
)


class FormPageRenderingTests(GarbageFormMixin, TestCase):
    """Opening every form page must be clean, with hostile ?next= too."""

    def test_form_pages_open_cleanly(self):
        urls = (
            reverse("users:login"),
            reverse("users:register"),
            reverse("users:password_reset"),
            reverse("catalog:search"),
        )
        for url in urls:
            response = self.client.get(url, {"next": "//evil.example.com"})
            self.assertEqual(response.status_code, 200, url)
            self.assert_no_system_text(response, url)

    def test_login_page_escapes_next(self):
        response = self.client.get(reverse("users:login"), {"next": '" onfocus="alert(1)'})
        self.assertEqual(response.status_code, 200)
        body = _body(response)
        self.assertNotIn('" onfocus="alert(1)', body)


class LoginFormGarbageTests(GarbageFormMixin, TestCase):
    def test_garbage_email_readable(self):
        response = self.client.post(reverse("users:login"), {"username": "не-почта", "password": "x"})
        self.assertEqual(response.status_code, 200)
        self.assert_readable_errors(response, "вход: мусор в почте")
        self.assert_survived(response, "вход: мусор в почте")

    def test_empty_credentials_readable(self):
        response = self.client.post(reverse("users:login"), {})
        self.assertEqual(response.status_code, 200)
        self.assert_readable_errors(response, "вход: пустые поля")
        self.assert_survived(response, "вход: пустые поля")

    def test_overlong_and_hostile_emails(self):
        for email in PAYLOADS:
            with self.subTest(email=email[:20]):
                response = self.client.post(reverse("users:login"), {"username": email, "password": "x"})
                self.assertEqual(response.status_code, 200)
                self.assert_survived(response, "вход: длинная почта")
                self.assertNotIn("<script>alert(1)</script>", _body(response))

    def test_overlong_password(self):
        response = self.client.post(reverse("users:login"), {"username": "a@example.com", "password": "п" * 10_000})
        self.assertEqual(response.status_code, 200)
        self.assert_survived(response, "вход: длинный пароль")

    def test_control_characters_in_password(self):
        response = self.client.post(reverse("users:login"), {"username": "a@example.com", "password": "\x00\x01\x02"})
        self.assertEqual(response.status_code, 200)
        self.assert_survived(response, "вход: управляющие символы в пароле")

    def test_hostile_next_not_followed(self):
        for target in ("https://evil.example.com", "//evil.example.com", "javascript:alert(1)"):
            with self.subTest(next=target):
                response = self.client.post(
                    reverse("users:login"),
                    {"username": "a@example.com", "password": "x", "next": target},
                )
                self.assertEqual(response.status_code, 200)
                self.assert_survived(response, "вход: чужой next")


class RegisterFormGarbageTests(GarbageFormMixin, TestCase):
    def _post(self, **overrides):
        data = {
            "email": "new@example.com",
            "username": "new_user",
            "password1": "Strong-Pass-2026!",
            "password2": "Strong-Pass-2026!",
        }
        data.update(overrides)
        return self.client.post(reverse("users:register"), data)

    def test_empty_form_readable(self):
        response = self.client.post(reverse("users:register"), {})
        self.assertEqual(response.status_code, 200)
        self.assert_readable_errors(response, "регистрация: пустая форма")
        self.assert_survived(response, "регистрация: пустая форма")

    def test_script_username_escaped(self):
        response = self._post(username="<script>alert(1)</script>")
        self.assertEqual(response.status_code, 200)
        self.assert_survived(response, "регистрация: скрипт в имени")
        self.assertNotIn("<script>alert(1)</script>", _body(response))

    def test_hostile_values_never_create_user(self):
        from django.contrib.auth import get_user_model

        before = get_user_model().objects.count()
        for payload in PAYLOADS:
            with self.subTest(payload=payload[:12]):
                self._post(email=payload, username=payload)
        self.assertEqual(get_user_model().objects.count(), before)

    def test_password_mismatch_readable(self):
        response = self._post(password2="Other-Pass-2026!")
        self.assertEqual(response.status_code, 200)
        body = _body(response)
        self.assertIn("form__error", body)
        self.assert_survived(response, "регистрация: пароли не совпали")

    def test_weak_passwords_explained(self):
        for password in ("12345678", "password"):
            with self.subTest(password=password):
                response = self._post(password1=password, password2=password)
                self.assertEqual(response.status_code, 200)
                self.assert_readable_errors(response, "регистрация: слабый пароль")
                self.assert_survived(response, "регистрация: слабый пароль")

    def test_duplicate_email_readable(self):
        create_user(email="taken@example.com")
        response = self._post(email="TAKEN@example.com")
        self.assertEqual(response.status_code, 200)
        body = _body(response)
        self.assertIn("уже зарегистрирован", body)

    def test_overlong_username(self):
        response = self._post(username="u" * 300)
        self.assertEqual(response.status_code, 200)
        self.assert_readable_errors(response, "регистрация: длинное имя")
        self.assert_survived(response, "регистрация: длинное имя")


class PasswordResetGarbageTests(GarbageFormMixin, TestCase):
    def test_reset_form_garbage_email(self):
        response = self.client.post(reverse("users:password_reset"), {"email": "\x00мусор"})
        self.assertIn(response.status_code, (200, 302))
        self.assert_survived(response, "сброс пароля: мусорная почта")

    def test_reset_form_overlong_email(self):
        response = self.client.post(reverse("users:password_reset"), {"email": "a" * 5000 + "@example.com"})
        self.assertIn(response.status_code, (200, 302))
        self.assert_survived(response, "сброс пароля: длинная почта")

    def test_garbage_reset_link_readable(self):
        for uidb64, token in (("abcd", "abcd"), ("!!!", "!!!"), ("a" * 400, "b" * 400)):
            with self.subTest(uidb64=uidb64[:8]):
                url = reverse("users:password_reset_confirm", args=[uidb64, token])
                response = self.client.get(url)
                self.assertIn(response.status_code, (200, 404), url)
                self.assert_survived(response, "сброс пароля: битая ссылка")


class ProfileFormGarbageTests(GarbageFormMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = create_user()
        self.client.force_login(self.user)

    def test_garbage_username_readable(self):
        response = self.client.post(reverse("users:profile"), {"username": "###", "bio": ""})
        self.assertEqual(response.status_code, 200)
        self.assert_readable_errors(response, "профиль: мусорное имя")
        self.assert_survived(response, "профиль: мусорное имя")

    def test_overlong_bio_readable_and_not_saved(self):
        response = self.client.post(reverse("users:profile"), {"username": self.user.username, "bio": "ы" * 50_000})
        self.assertEqual(response.status_code, 200)
        self.assert_readable_errors(response, "профиль: длинное био")
        self.assert_survived(response, "профиль: длинное био")
        self.user.refresh_from_db()
        self.assertEqual(self.user.bio, "")

    def test_nul_byte_in_bio_not_stored(self):
        response = self.client.post(
            reverse("users:profile"),
            {"username": self.user.username, "bio": "привет\x00мир"},
        )
        self.assertIn(response.status_code, (200, 302))
        self.assert_survived(response, "профиль: NUL в био")
        self.user.refresh_from_db()
        if response.status_code == 302:
            self.assertNotIn("\x00", self.user.bio)

    def test_text_file_as_avatar_readable(self):
        avatar = SimpleUploadedFile("avatar.jpg", b"definitely not an image", content_type="image/jpeg")
        response = self.client.post(
            reverse("users:profile"),
            {"username": self.user.username, "bio": "", "avatar": avatar},
        )
        self.assertEqual(response.status_code, 200)
        self.assert_readable_errors(response, "профиль: не-картинка в аватаре")
        self.assert_survived(response, "профиль: не-картинка в аватаре")
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)

    def test_truncated_png_as_avatar_readable(self):
        avatar = SimpleUploadedFile("avatar.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, content_type="image/png")
        response = self.client.post(
            reverse("users:profile"),
            {"username": self.user.username, "bio": "", "avatar": avatar},
        )
        self.assertEqual(response.status_code, 200)
        self.assert_readable_errors(response, "профиль: битый PNG")
        self.assert_survived(response, "профиль: битый PNG")

    def test_zero_byte_avatar_readable(self):
        avatar = SimpleUploadedFile("empty.jpg", b"", content_type="image/jpeg")
        response = self.client.post(
            reverse("users:profile"),
            {"username": self.user.username, "bio": "", "avatar": avatar},
        )
        self.assertEqual(response.status_code, 200)
        self.assert_readable_errors(response, "профиль: пустой файл")
        self.assert_survived(response, "профиль: пустой файл")

    def test_oversized_image_readable(self):
        # Uncompressed BMP: 2000x1000x3 bytes ≈ 5.7 MB, over the 5 MB limit.
        buffer = BytesIO()
        Image.new("RGB", (2000, 1000), "red").save(buffer, format="BMP")
        avatar = SimpleUploadedFile("big.bmp", buffer.getvalue(), content_type="image/bmp")
        response = self.client.post(
            reverse("users:profile"),
            {"username": self.user.username, "bio": "", "avatar": avatar},
        )
        self.assertEqual(response.status_code, 200)
        self.assert_readable_errors(response, "профиль: файл больше лимита")
        self.assert_survived(response, "профиль: файл больше лимита")

    def test_traversal_avatar_filename_no_crash(self):
        buffer = BytesIO()
        Image.new("RGB", (16, 16), "blue").save(buffer, format="PNG")
        avatar = SimpleUploadedFile("../../evil.png", buffer.getvalue(), content_type="image/png")
        response = self.client.post(
            reverse("users:profile"),
            {"username": self.user.username, "bio": "", "avatar": avatar},
        )
        self.assertIn(response.status_code, (200, 302))
        self.assert_survived(response, "профиль: обход пути в имени файла")
        self.user.refresh_from_db()
        if self.user.avatar:
            self.assertNotIn("..", self.user.avatar.name)


class ReviewFormGarbageTests(GarbageFormMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = create_user()
        self.client.force_login(self.user)
        self.title = create_title()

    def test_garbage_rating_readable(self):
        for rating in ("отлично", "1e999", "999", "-1", ""):
            with self.subTest(rating=rating):
                response = self.client.post(
                    reverse("reviews:save", args=[self.title.slug]),
                    {"rating": rating, "text": "текст"},
                )
                self.assertEqual(response.status_code, 400)
                self.assert_readable_errors(response, "отзыв: мусорная оценка")
                self.assert_survived(response, "отзыв: мусорная оценка")
        self.assertEqual(Review.objects.filter(title=self.title).count(), 0)

    def test_overlong_text_readable(self):
        response = self.client.post(
            reverse("reviews:save", args=[self.title.slug]),
            {"rating": "8", "text": "ы" * 5000},
        )
        self.assertEqual(response.status_code, 400)
        self.assert_readable_errors(response, "отзыв: длинный текст")
        self.assert_survived(response, "отзыв: длинный текст")

    def test_script_text_escaped_on_page(self):
        response = self.client.post(
            reverse("reviews:save", args=[self.title.slug]),
            {"rating": "8", "text": "<script>alert(1)</script>"},
        )
        self.assertIn(response.status_code, (200, 302))
        page = self.client.get(self.title.get_absolute_url())
        self.assertNotIn("<script>alert(1)</script>", _body(page))

    def test_nul_byte_in_text_not_stored(self):
        response = self.client.post(
            reverse("reviews:save", args=[self.title.slug]),
            {"rating": "8", "text": "Мне\x00понравилось"},
        )
        self.assertIn(response.status_code, (200, 302, 400))
        self.assert_survived(response, "отзыв: NUL в тексте")
        review = Review.objects.filter(title=self.title, user=self.user).first()
        if review:
            self.assertNotIn("\x00", review.text)


class CommentFormGarbageTests(GarbageFormMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = create_user()
        self.client.force_login(self.user)
        self.title = create_title()

    def _post(self, **overrides):
        data = {"text": "привет", "parent": ""}
        data.update(overrides)
        return self.client.post(reverse("reviews:comment_add", args=[self.title.slug]), data)

    def test_empty_text_readable(self):
        response = self._post(text="")
        self.assertEqual(response.status_code, 400)
        self.assert_readable_errors(response, "комментарий: пустой текст")
        self.assert_survived(response, "комментарий: пустой текст")
        self.assertEqual(self.title.comments.count(), 0)

    def test_overlong_text_readable(self):
        response = self._post(text="ы" * 5000)
        self.assertEqual(response.status_code, 400)
        self.assert_readable_errors(response, "комментарий: длинный текст")
        self.assert_survived(response, "комментарий: длинный текст")

    def test_tampered_parent_never_crashes(self):
        for parent in ("abc", "-1", "1.5", "9" * 30, "1\x00", "'; DROP TABLE reviews_comment; --", "NaN"):
            with self.subTest(parent=parent[:16]):
                response = self._post(parent=parent)
                self.assertIn(response.status_code, (200, 302, 400))
                self.assert_survived(response, "комментарий: испорченный parent")

    def test_parent_from_other_title_ignored(self):
        other = create_title()
        foreign = Comment.objects.create(user=self.user, title=other, text="чужой")
        response = self._post(parent=str(foreign.pk))
        self.assertIn(response.status_code, (200, 302))
        created = Comment.objects.get(title=self.title)
        self.assertIsNone(created.parent)

    def test_nul_byte_in_text_not_stored(self):
        response = self._post(text="текст\x00с нулём")
        self.assertIn(response.status_code, (200, 302, 400))
        self.assert_survived(response, "комментарий: NUL в тексте")
        if response.status_code == 302:
            comment = Comment.objects.get(title=self.title)
            self.assertNotIn("\x00", comment.text)


class ToggleButtonGarbageTests(GarbageFormMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = create_user()
        self.client.force_login(self.user)
        self.title = create_title()

    def test_hostile_next_never_leaves_site(self):
        for target in ("https://evil.example.com", "//evil.example.com", "javascript:alert(1)", "\x00\x01//evil"):
            with self.subTest(next=target):
                response = self.client.post(
                    reverse("library:toggle_favorite", args=[self.title.slug]),
                    {"next": target},
                )
                self.assertEqual(response.status_code, 302)
                self.assertNotIn("evil", response["Location"])

    def test_json_path_survives_garbage_next(self):
        response = self.client.post(
            reverse("library:toggle_watchlist", args=[self.title.slug]),
            {"next": "https://evil.example.com"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("is_watchlist", response.json())

    def test_missing_slug_404_readable(self):
        for name in ("library:toggle_favorite", "library:toggle_watchlist"):
            response = self.client.post(reverse(name, args=["no-such-title-9999"]))
            self.assertEqual(response.status_code, 404)
            self.assert_survived(response, f"{name}: несуществующий фильм")

    def test_clear_history_methods(self):
        get_response = self.client.get(reverse("library:clear_history"))
        self.assertEqual(get_response.status_code, 405)
        self.assert_survived(get_response, "история: GET на очистку")
        post_response = self.client.post(reverse("library:clear_history"))
        self.assertEqual(post_response.status_code, 302)


class LanguageSwitcherGarbageTests(GarbageFormMixin, TestCase):
    def test_garbage_language_never_crashes(self):
        for language in ("zz", "z" * 1000, "\x00", "ru;DROP", "🔥", ""):
            with self.subTest(language=language[:12]):
                response = self.client.post(reverse("set_language"), {"language": language, "next": "/"})
                self.assertIn(response.status_code, (200, 302))
                self.assert_survived(response, "язык: мусорный код")

    def test_hostile_next_not_followed(self):
        for target in ("https://evil.example.com", "//evil.example.com"):
            with self.subTest(next=target):
                response = self.client.post(reverse("set_language"), {"language": "en", "next": target})
                self.assertIn(response.status_code, (200, 302))
                location = response.get("Location", "")
                self.assertNotIn("evil", location)


class SearchAndFilterGarbageTests(GarbageFormMixin, TestCase):
    def setUp(self):
        super().setUp()
        create_title()

    def test_search_survives_garbage(self):
        for payload in PAYLOADS:
            with self.subTest(payload=payload[:12]):
                response = self.client.get(reverse("catalog:search"), {"q": payload})
                self.assertEqual(response.status_code, 200)
                self.assert_survived(response, "поиск: мусорный запрос")

    def test_search_query_not_injected_raw(self):
        response = self.client.get(reverse("catalog:search"), {"q": "<script>alert(1)</script>"})
        self.assertNotIn("<script>alert(1)</script>", _body(response))

    def test_catalog_filters_survive_garbage(self):
        cases = (
            {"page": "abc"},
            {"page": "-1"},
            {"page": "9" * 30},
            {"rating_from": "abc"},
            {"year_from": "abc", "year_to": "1e999"},
            {"sort": "'; DROP TABLE catalog_title; --"},
            {"sort": ["-views_count", "garbage"]},
            {"genre": "нет-такого-жанра-9999"},
            {"q": "ы" * 10_000},
            {"voice": "\x00"},
        )
        for params in cases:
            with self.subTest(params=str(params)[:40]):
                response = self.client.get(reverse("catalog:title_list"), params)
                self.assertIn(response.status_code, (200, 404))
                self.assert_survived(response, "каталог: мусорные фильтры")

    def test_actor_search_survives_garbage(self):
        for payload in ("ы" * 5000, "\x00", "'; DROP TABLE catalog_person; --", "🔥"):
            with self.subTest(payload=payload[:12]):
                response = self.client.get(
                    reverse("catalog:actor_search"),
                    {"q": payload},
                    HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                )
                self.assertIn(response.status_code, (200, 404))
                self.assert_survived(response, "поиск по актёру: мусор")


class ApiMalformedBodyTests(GarbageFormMixin, TestCase):
    """Malformed bodies must come back as 4xx JSON, not as a crash."""

    def setUp(self):
        super().setUp()
        self.user = create_user()
        self.client.force_login(self.user)
        self.title = create_title()

    def test_rate_endpoint_malformed_bodies(self):
        cases = ('{"rating": ', "{", "null", "[]", '{"rating": 8, }', '{"rating": "8\x00"}')
        for body in cases:
            with self.subTest(body=body[:20]):
                response = self.client.post(
                    f"/api/v1/titles/{self.title.slug}/rate/",
                    data=body,
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertNotEqual(response.get("Content-Type", "").split(";")[0], "text/html")

    def test_watch_endpoint_malformed_bodies(self):
        for body in ("{", "[]", '{"position": "abc"}', '{"position": -5}'):
            with self.subTest(body=body[:20]):
                response = self.client.post(
                    f"/api/v1/titles/{self.title.slug}/watch/",
                    data=body,
                    content_type="application/json",
                )
                self.assertIn(response.status_code, (200, 400))

    def _post_comment(self, parent):
        return self.client.post(
            f"/api/v1/titles/{self.title.slug}/comments/",
            data=json.dumps({"text": "привет", "parent": parent}),
            content_type="application/json",
        )

    def test_api_parent_out_of_range_rejected(self):
        """Номер за границей bigint отсекается до запроса к базе.

        Сравниваем ответ на 2**63 с ответом на ноль: ноль заведомо не
        доходит до выборки, поэтому совпадение означает «вне диапазона».
        Проверка нарочно не смотрит на формулировку: именно так проходил
        прежний вариант защиты, который DRF обходил, — сообщение было
        русским («объект не существует»), и тест считал это успехом.
        """
        zero = self._post_comment(0)
        too_big = self._post_comment(2**63)
        missing = self._post_comment(99999999)

        self.assertEqual(too_big.status_code, 400)
        self.assertEqual(
            too_big.json()["parent"],
            zero.json()["parent"],
            "номер больше bigint обработан не как «вне диапазона» — значит, ушёл в запрос",
        )
        self.assertNotEqual(
            too_big.json()["parent"],
            missing.json()["parent"],
            "запредельный и просто несуществующий номер дали один ответ",
        )

    def test_api_parent_garbage_types_rejected(self):
        for parent in ("abc", True, [12], {"id": 1}, -1, 0, "1.5"):
            with self.subTest(parent=parent):
                response = self.client.post(
                    f"/api/v1/titles/{self.title.slug}/comments/",
                    data=json.dumps({"text": "привет", "parent": parent}),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
        self.assertEqual(Comment.objects.filter(title=self.title).count(), 0)

    def test_api_text_with_nul_rejected(self):
        review = self.client.post(
            f"/api/v1/titles/{self.title.slug}/reviews/",
            data=json.dumps({"rating": 8, "text": "Мне\u0000нравится"}),
            content_type="application/json",
        )
        self.assertEqual(review.status_code, 400)
        comment = self.client.post(
            f"/api/v1/titles/{self.title.slug}/comments/",
            data=json.dumps({"text": "текст\u0000с нулём"}),
            content_type="application/json",
        )
        self.assertEqual(comment.status_code, 400)
        self.assertEqual(Review.objects.filter(title=self.title).count(), 0)
        self.assertEqual(Comment.objects.filter(title=self.title).count(), 0)
