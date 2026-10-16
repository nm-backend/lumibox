"""Crawl of every route with garbage, the way a confused visitor would click.

The form tests cover the fields; this module covers the *buttons*: each URL
in the project is opened with rubbish substituted into every path converter
and with a nonsense query string, then the same route is POSTed with a body
full of nonsense. Two properties are asserted for every response:

* no 500 — the site answers with a page, not with a crash;
* no raw system text — no traceback, no framework exception name, no
  Django debug page, no English validation fallback.

Routes are collected from the URL resolver, so a new view is covered by this
test the moment it is wired up, without anyone remembering to add it here.
"""

import re
import urllib.parse

from django.core.cache import cache
from django.http import HttpResponse
from django.test import Client, TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from apps.core.test_factories import (
    create_collection,
    create_country,
    create_genre,
    create_person,
    create_title,
    create_user,
)

# Stand-ins for each path converter. The integer is 2**63 — one past the
# bigint ceiling: PostgreSQL refuses such a literal before it can return
# "no rows", so this is the value most likely to crash a lookup.
GARBAGE_BY_CONVERTER = {
    "int": "9223372036854775808",
    "slug": "мусор-на-этом-месте",
    "str": "мусор",
    "uuid": "not-a-uuid",
    "path": "..%2F..%2Fetc%2Fpasswd",
}

# Rubbish a human can actually produce: wrong format, foreign alphabet,
# huge value, control characters, markup, SQL, an emoji, a lone space.
PAYLOADS = (
    "ы" * 5_000,
    "<script>alert(1)</script>",
    "'; DROP TABLE catalog_title; --",
    "\x00\x01\x02",
    "🔥ёй漢字‮",
    "9223372036854775808",
    "1e999",
    "   ",
)

# Anything here in a response means the visitor is reading our internals.
SYSTEM_MARKERS = (
    "Traceback (most recent call last)",
    "Exception Value",
    "Exception Type",
    "Request Method:",
    "Django Version",
    "Python Executable",
    "Settings module",
    "Server Error (500)",
    "TemplateDoesNotExist",
    "TemplateSyntaxError",
    "NoReverseMatch",
    "ImproperlyConfigured",
    "OperationalError",
    "ProgrammingError",
    "IntegrityError",
    "DataError",
    "FieldError",
    "TypeError",
    "ValueError",
    "AttributeError",
    "KeyError",
    "IndexError",
    "UnboundLocalError",
    "psycopg",
    "django.core.exceptions",
    "This field is required",
    "Enter a valid",
    "Ensure this value",
    "<!DOCTYPE html>\n<html lang=\"en\">",
)

CONVERTER_TOKEN = re.compile(r"<(?:(?P<converter>[a-z]+):)?(?P<name>[a-zA-Z_]\w*)>")


def _concretize(pattern):
    """Turn a URL pattern into a requestable path full of garbage."""
    return CONVERTER_TOKEN.sub(
        lambda match: GARBAGE_BY_CONVERTER.get(match.group("converter") or "str", "мусор"),
        pattern,
    )


def _iter_routes(patterns=None, prefix=""):
    """Yield (path, name) for every pattern in the project, recursively."""
    if patterns is None:
        patterns = get_resolver().url_patterns
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from _iter_routes(entry.url_patterns, prefix + str(entry.pattern))
        elif isinstance(entry, URLPattern):
            yield prefix + str(entry.pattern), entry.name or "(без имени)"


def _all_routes():
    routes = sorted(set(_iter_routes()))
    assert len(routes) > 20, "маршруты не собрались — краулер бесполезен"
    return routes


class RouteCrawlMixin:
    """Общий каркас: клиент, тестовые объекты и проверка ответа.

    Метка аудита — по ней набор выделяется в отдельный шаг CI. Живёт на
    общем предке, поэтому под неё попадает и любой новый тест модуля.
    """

    tags = ("adversarial",)

    def setUp(self):
        cache.clear()
        super().setUp()
        self.client = Client(raise_request_exception=False)
        self.title = create_title()
        self.user = create_user()

    def _check(self, response, label):
        self.assertNotEqual(response.status_code, 500, f"{label}: ответ 500 (страница падения)")
        body = response.content.decode("utf-8", errors="replace")
        for marker in SYSTEM_MARKERS:
            self.assertNotIn(marker, body, f"{label}: в ответе системный текст {marker!r}")

    def _garbage_query(self, payload):
        return {
            "q": payload,
            "page": payload,
            "sort": payload,
            "year_from": payload,
            "year_to": payload,
            "rating_from": payload,
            "genre": payload,
            "next": "//evil.example.com",
            "language": payload,
            "format": payload,
        }


class AnonymousRouteCrawlTests(RouteCrawlMixin, TestCase):
    def test_every_route_opens_with_garbage_in_path_and_query(self):
        for path, name in _all_routes():
            url = urllib.parse.quote(_concretize(path), safe="/")
            for payload in ("мусор", "<script>alert(1)</script>", "9223372036854775808", "\x00\x01"):
                with self.subTest(route=name, url=url, payload=payload[:14]):
                    response = self.client.get(url, self._garbage_query(payload))
                    self._check(response, f"{name} [{url}]")

    def test_every_route_survives_repeated_slashes_and_dots(self):
        for path, name in _all_routes():
            url = urllib.parse.quote(_concretize(path), safe="/")
            for suffix in ("//", "/./", "/../", "%2e%2e/", "?", "#", "//..//..//"):
                with self.subTest(route=name, suffix=suffix):
                    response = self.client.get(url + suffix)
                    self._check(response, f"{name} [{url}{suffix}]")

    def test_added_methods_do_not_leak_system_text(self):
        for path, name in _all_routes():
            url = urllib.parse.quote(_concretize(path), safe="/")
            with self.subTest(route=name):
                response = self.client.post(url, {"q": "мусор", "text": "\x00", "parent": "abc"})
                self._check(response, f"POST {name} [{url}]")


class AuthenticatedRouteCrawlTests(RouteCrawlMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_every_route_opens_cleanly_when_logged_in(self):
        for path, name in _all_routes():
            url = urllib.parse.quote(_concretize(path), safe="/")
            for payload in PAYLOADS:
                with self.subTest(route=name, payload=payload[:14]):
                    response = self.client.get(url, self._garbage_query(payload))
                    self._check(response, f"{name} [{url}] (вошедший)")

    def test_every_route_survives_a_garbage_post_when_logged_in(self):
        """A logged-in visitor can post to far more routes — check them all."""
        body = {
            "text": "ы" * 5_000,
            "rating": "1e999",
            "parent": "9" * 30,
            "email": "не-почта",
            "username": "\x00мусор",
            "password1": "x",
            "password2": "y",
            "next": "https://evil.example.com",
            "q": "' OR 1=1 --",
        }
        for path, name in _all_routes():
            # Выход из аккаунта — штатное действие кнопки, а не вход с мусором:
            # после него остальные запросы ушли бы от анонима.
            if name == "logout":
                continue
            url = urllib.parse.quote(_concretize(path), safe="/")
            with self.subTest(route=name):
                if not self.client.session.get("_auth_user_id"):
                    self.client.force_login(self.user)
                response = self.client.post(url, body)
                self._check(response, f"POST {name} [{url}] (вошедший)")

    def test_explicit_delete_buttons_with_garbage_ids(self):
        """Кнопки удаления — единственные, что реально стирают данные."""
        comment_target = f"/api/v1/titles/{self.title.slug}/comments/"
        self.client.post(
            comment_target,
            data='{"text": "комментарий"}',
            content_type="application/json",
        )
        for garbage in ("0", "-1", "abc", "9223372036854775808", "9" * 40, "1\x00"):
            with self.subTest(garbage=garbage[:16]):
                for url in (
                    f"/reviews/review/{urllib.parse.quote(garbage)}/delete/",
                    f"/reviews/comment/{urllib.parse.quote(garbage)}/delete/",
                    f"/api/v1/titles/{self.title.slug}/comments/{urllib.parse.quote(garbage)}/",
                ):
                    response = self.client.post(url) if "/api/" not in url else self.client.delete(url)
                    self._check(response, f"удаление [{url}]")


class RealPagesStillWorkTests(RouteCrawlMixin, TestCase):
    """Дымовая проверка самого краулера: без неё «ноль падений» означало бы
    лишь то, что мы ни разу не попали на настоящую страницу."""

    def test_main_pages_render_for_real_objects(self):
        genre = create_genre()
        country = create_country()
        person = create_person()
        collection = create_collection(titles=[self.title])

        pages = (
            (reverse("catalog:home"), 200),
            (reverse("catalog:title_list"), 200),
            (reverse("catalog:title_detail", args=[self.title.slug]), 200),
            (reverse("catalog:genre_titles", args=[genre.slug]), 200),
            (reverse("catalog:country_titles", args=[country.slug]), 200),
            (reverse("catalog:person_detail", args=[person.slug]), 200),
            (reverse("catalog:collection_detail", args=[collection.slug]), 200),
            (reverse("catalog:search"), 200),
            (reverse("catalog:new"), 200),
            (reverse("catalog:top"), 200),
        )
        for url, expected in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, expected, url)
                self._check(response, url)

    def test_checker_notices_system_text(self):
        """Проверка проверки: страница падения обязана быть замечена."""
        broken = HttpResponse(
            "Traceback (most recent call last):\n"
            "  File \"/app/apps/catalog/views.py\", line 42\n"
            "TypeError: unsupported operand type(s)\n"
            "Exception Value: TypeError\n"
            "Django Version: 5.2\n"
        )
        with self.assertRaises(AssertionError):
            self._check(broken, "канарейка")
        with self.assertRaises(AssertionError):
            self._check(HttpResponse("Server Error (500)", status=500), "канарейка-500")
