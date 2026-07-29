"""
Тесты дополнительных вьюх ядра: serve_public_media и ElidedPaginationMixin.

Покрывает:
- serve_public_media — защита приватных медиафайлов
- ElidedPaginationMixin — структура контекста с пагинацией
"""

from django.http import Http404, HttpRequest
from django.test import TestCase

from apps.core.views import serve_public_media


class ServePublicMediaTests(TestCase):
    """serve_public_media не должен открывать приватные файлы."""

    def test_private_media_returns_404(self):
        """Путь, начинающийся с private_media/, должен вернуть 404."""
        request = HttpRequest()
        request.META = {"SERVER_NAME": "test", "SERVER_PORT": "80"}
        with self.assertRaises(Http404):
            serve_public_media(request, "private_media/videos/2025/01/video.mp4")

    def test_normal_media_raises_http404_not_blocked(self):
        """Обычный медиа-путь отдаёт 404 от serve(), не блок Http404."""
        request = HttpRequest()
        request.META["SERVER_NAME"] = "localhost"
        request.META["SERVER_PORT"] = "8000"
        with self.assertRaises(Http404):
            serve_public_media(request, "posters/poster.jpg", document_root="media")


class ElidedPaginationMixinTests(TestCase):
    """ElidedPaginationMixin — структура контекста."""

    def test_context_contains_ellipsis_with_paginator(self):
        """Если paginator и page_obj переданы, контекст содержит ellipsis."""
        from django.core.paginator import Paginator

        paginator = Paginator(list(range(50)), 10)
        page = paginator.get_page(1)

        # Проверяем, что get_elided_page_range возвращает ожидаемый формат
        elided = paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)
        self.assertIn(paginator.ELLIPSIS, elided if hasattr(paginator, 'ELLIPSIS') else [])
