"""
Создаёт тестовый фильм с видеоресурсом для healthcheck плеера.

Команда создаёт минимальную запись фильма и привязывает к нему
тестовый видеоресурс с внешним провайдером (R2), чтобы страница
плеера гарантированно рендерилась без 404.

Использование:
    python manage.py seed_player_test_data

Переменные окружения (обязательно задать ДО запуска):
    CLOUDFLARE_R2_DELIVERY_BASE_URL
        — адрес CDN для доставки тестового видео.
        Если не задан, плеер покажет «Источник видео пока недоступен»,
        но страница отрендерится без 404.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Title
from apps.streaming.models import VideoAsset

TEST_MOVIE_SLUG = "test-player-movie"


class Command(BaseCommand):
    help = "Создаёт тестовый фильм с видеоресурсом для healthcheck плеера."

    def handle(self, *args, **options):
        self._warn_if_no_provider()
        self._create_test_movie()
        self.stdout.write(self.style.SUCCESS(f"Тестовый фильм создан: /watch/{TEST_MOVIE_SLUG}/"))

    @transaction.atomic
    def _create_test_movie(self):
        title, _ = Title.objects.update_or_create(
            slug=TEST_MOVIE_SLUG,
            defaults={
                "name": "Тестовый фильм плеера",
                "type": Title.Type.MOVIE,
                "status": Title.Status.PUBLISHED,
                "release_year": 2026,
                "description": "Тестовый фильм для healthcheck страницы плеера.",
                "short_description": "Healthcheck-фильм для проверки работы плеера.",
                "duration_minutes": 2,
            },
        )

        VideoAsset.objects.update_or_create(
            title=title,
            defaults={
                "provider": VideoAsset.Provider.CLOUDFLARE_R2,
                "stream_type": VideoAsset.StreamType.MP4,
                "asset_key": "healthcheck/test-video.mp4",
                "status": VideoAsset.Status.READY,
                "access_level": VideoAsset.AccessLevel.FREE,
                "duration_seconds": 120,
                "available_qualities": ["auto", "1080p", "720p", "480p"],
            },
        )

        self.stdout.write(f"Создан фильм: {title.name} (slug={title.slug})")

    def _warn_if_no_provider(self):
        """Предупреждает, если CLOUDFLARE_R2_DELIVERY_BASE_URL не задан.

        Переменная окружения должна быть установлена ДО запуска manage.py:
        settings.base.STREAMING_PROVIDER_CONFIG читается при загрузке модуля,
        и задать её изнутри handle() уже нельзя.
        """
        config = getattr(settings, "STREAMING_PROVIDER_CONFIG", {})
        r2_config = config.get("cloudflare_r2", {})

        if not r2_config.get("delivery_base_url"):
            self.stdout.write(
                self.style.WARNING(
                    "CLOUDFLARE_R2_DELIVERY_BASE_URL не задан. "
                    "Плеер покажет 'Источник видео пока недоступен', "
                    "но страница отрендерится. "
                    "Задайте переменную окружения ДО запуска manage.py:\n"
                    "  export CLOUDFLARE_R2_DELIVERY_BASE_URL=https://media.example.com"
                )
            )
