"""
Тесты Content-Security-Policy middleware.

Проверяем, что заголовок присутствует на каждом ответе и содержит
все ключевые директивы. CSP — последний рубеж защиты от XSS, и его
отсутствие или ослабление должно быть замечено тестами.
"""

from django.test import Client, TestCase
from django.urls import reverse


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
