"""
Тесты Content-Security-Policy middleware.

Проверяем, что заголовок присутствует на каждом ответе и содержит
все ключевые директивы. CSP — последний рубеж защиты от XSS, и его
отсутствие или ослабление должно быть замечено тестами.
"""

from django.db import connection
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.core.middleware import QueryStringSanitizerMiddleware


class CSPMiddlewareTests(TestCase):
    """CSP-заголовок на каждой странице, не только на /healthz/."""

    def setUp(self):
        self.client = Client()

    def _check_csp_header(self, url):
        response = self.client.get(url)
        csp = response.get("Content-Security-Policy")
        self.assertIsNotNone(csp, f"CSP header missing on {url}")
        return csp

    def test_home_page_has_csp(self):
        """Главная страница должна иметь CSP."""
        self._check_csp_header(reverse("catalog:home"))

    def test_catalog_page_has_csp(self):
        """Страница каталога должна иметь CSP."""
        self._check_csp_header(reverse("catalog:title_list"))

    def test_health_check_has_csp(self):
        """Даже health-check должен иметь CSP."""
        self._check_csp_header("/healthz/")

    def test_404_page_has_csp(self):
        """Несуществующая страница тоже должна иметь CSP."""
        self._check_csp_header("/this-path-does-not-exist-12345/")

    def test_csp_contains_self(self):
        """default-src должен разрешать 'self'."""
        csp = self._check_csp_header(reverse("catalog:home"))
        self.assertIn("default-src 'self'", csp)

    def test_csp_contains_script_self(self):
        """script-src должен разрешать 'self'."""
        csp = self._check_csp_header(reverse("catalog:home"))
        self.assertIn("script-src 'self'", csp)

    def test_csp_allows_inline_styles(self):
        """style-src должен разрешать inline-стили для админки."""
        csp = self._check_csp_header(reverse("catalog:home"))
        self.assertIn("style-src 'self' 'unsafe-inline'", csp)

    def test_csp_allows_external_images(self):
        """img-src должен разрешать https для постеров с CDN."""
        csp = self._check_csp_header(reverse("catalog:home"))
        self.assertIn("img-src 'self' data: https:", csp)

    def test_csp_allows_embeds(self):
        """frame-src должен разрешать YouTube, Vimeo и Rutube — всех встраиваемых хостингов embeds.py."""
        csp = self._check_csp_header(reverse("catalog:home"))
        self.assertIn("frame-src 'self'", csp)
        self.assertIn("youtube.com", csp)
        self.assertIn("vimeo.com", csp)
        self.assertIn("rutube.ru", csp)

    def test_csp_allows_external_player(self):
        """script-src и frame-src должны разрешать внешний плеер (SDK и его iframe)."""
        csp = self._check_csp_header(reverse("catalog:home"))
        self.assertIn("graphicslab.io", csp)
        self.assertIn("kinescopecdn.net", csp)
        self.assertIn("videoframe2.com", csp)

    def test_csp_blocks_objects(self):
        """object-src должен быть 'none' — Flash и плагины не нужны."""
        csp = self._check_csp_header(reverse("catalog:home"))
        self.assertIn("object-src 'none'", csp)

    def test_csp_restricts_base_uri(self):
        """base-uri должен быть 'self' — нельзя переопределить базу через <base>."""
        csp = self._check_csp_header(reverse("catalog:home"))
        self.assertIn("base-uri 'self'", csp)

    def test_csp_restricts_form_action(self):
        """form-action должен быть 'self' — нельзя отправить форму на чужой домен."""
        csp = self._check_csp_header(reverse("catalog:home"))
        self.assertIn("form-action 'self'", csp)

    def test_csp_does_not_include_ads_when_disabled(self):
        """При выключенной рекламе в CSP нет доменов рекламной сети."""
        csp = self._check_csp_header(reverse("catalog:home"))
        self.assertNotIn("v-js-menu.run", csp)
        self.assertNotIn("ufouxbwn.com", csp)
        self.assertNotIn("timing-js-menu.xyz", csp)

    @override_settings(ADS_NETWORK_ENABLED=True)
    def test_csp_includes_ads_when_enabled(self):
        """При включённой рекламе CSP разрешает лоадер, движок и https-креативы."""
        csp = self._check_csp_header(reverse("catalog:home"))
        self.assertIn("v-js-menu.run", csp)
        self.assertIn("timing-js-menu.xyz", csp)
        self.assertIn("vast2.ufouxbwn.com", csp)
        self.assertIn("cdn7.ufouxbwn.com", csp)
        # https: в frame-src и connect-src — креативы и пиксели рекламодателей
        self.assertIn("frame-src 'self'", csp)
        self.assertIn("frame-src", csp)

    @override_settings(ADS_NETWORK_ENABLED=True)
    def test_csp_base_directives_survive_ads(self):
        """Включение рекламы не должно ослаблять остальные директивы."""
        csp = self._check_csp_header(reverse("catalog:home"))
        self.assertIn("object-src 'none'", csp)
        self.assertIn("base-uri 'self'", csp)
        self.assertIn("form-action 'self'", csp)
        self.assertIn("img-src 'self' data: https:", csp)


class RequestIdMiddlewareTests(TestCase):
    """X-Request-ID: генерация, проброс входящего, уникальность."""

    def setUp(self):
        self.client = Client()

    def test_response_has_request_id_header(self):
        """Каждый ответ содержит сгенерированный X-Request-ID."""
        response = self.client.get("/")
        self.assertIn("X-Request-ID", response)
        self.assertEqual(len(response["X-Request-ID"]), 16)

    def test_incoming_request_id_is_preserved(self):
        """Входящий X-Request-ID (от балансировщика/CDN) пробрасывается."""
        response = self.client.get("/", HTTP_X_REQUEST_ID="trace-123")
        self.assertEqual(response["X-Request-ID"], "trace-123")

    def test_request_id_differs_between_requests(self):
        """Два разных запроса получают разные ID."""
        first = self.client.get("/").headers["X-Request-ID"]
        second = self.client.get("/").headers["X-Request-ID"]
        self.assertNotEqual(first, second)


class QueryStringSanitizerTests(TestCase):
    """
    NUL в строке запроса не должен доходить до базы.

    PostgreSQL отказывается принимать символ NUL (0x00) в параметрах
    запроса — драйвер поднимает ValueError, и страница отвечает 500.
    SQLite такую строку пропускает, поэтому проверяем не код ответа
    (он и до правки был 200), а сами параметры SQL: в них не должно
    остаться NUL. Так тест падает и на SQLite — то есть проверяет то же
    требование, из-за которого падал CI на PostgreSQL.
    """

    def _sql_params(self, callback):
        """Выполняет запрос и собирает все параметры SQL за время запроса."""
        captured = []

        def wrapper(execute, sql, params, many, context):
            captured.append(params)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(wrapper):
            response = callback()

        flat = " ".join(str(part) for params in captured for part in (params or ()))
        return response, flat

    def test_middleware_removes_nul_from_query_parameters(self):
        """
        Прямая проверка middleware: до вьюхи параметр доходит без NUL.

        Это и есть канарейка: без middleware здесь останется «a\x00b»,
        и тест падает — в отличие от проверок по SQL, где часть путей
        и без чистки обходится своими валидаторами.
        """
        seen = {}

        def view(request):
            seen.update(dict(request.GET.items()))
            return HttpResponse("ok")

        response = QueryStringSanitizerMiddleware(view)(RequestFactory().get("/?q=a%00b&page=2"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen["q"], "ab")
        self.assertEqual(seen["page"], "2")

    def test_search_page_does_not_pass_nul_to_sql(self):
        response, params = self._sql_params(
            lambda: self.client.get(reverse("catalog:search"), {"q": "\x00\x01\x02"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("\x00", params)

    def test_catalog_genre_filter_does_not_pass_nul_to_sql(self):
        """
        Жанр ищется по slug — это тоже параметр из адреса.

        Без middleware проверка поля уходила в базу с NUL внутри:
        на SQLite незаметно, на PostgreSQL — 500.
        """
        response, params = self._sql_params(
            lambda: self.client.get(reverse("catalog:title_list"), {"genre": "drama\x00"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("\x00", params)

    def test_api_filter_does_not_pass_nul_to_sql(self):
        response, params = self._sql_params(
            lambda: self.client.get("/api/v1/titles/", {"genres__slug": "\x00drama"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("\x00", params)

    def test_clean_value_is_kept(self):
        """Чистка не портит само слово: мусор убирается, запрос остаётся."""
        response = self.client.get(reverse("catalog:search"), {"q": "Начало\x00"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["query"], "Начало")
