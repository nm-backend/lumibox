"""
Создаёт демо-видеоресурсы для всех опубликованных фильмов и сериалов.

Делает кнопку «Смотреть» рабочей: без VideoAsset она не появляется,
и половина проекта (плеер, continue watching, progress) остаётся мёртвым кодом.

Для фильмов: создаёт VideoAsset с типом HLS через Cloudflare Stream (демо).
Для сериалов: создаёт Season → Episode → VideoAsset.

Идемпотентна: повторный запуск не создаёт дубликаты.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.models import Title
from apps.streaming.models import Episode, Season, VideoAsset

# Публичный тестовый HLS-поток (Apple sample streams).
# Используется как заглушка: редактор заменит на реальные через админку.
# URL: https://devstreaming-cdn.apple.com/videosamples/examples/bipbop_16x9/bipbop_16x9_variant.m3u8
DEMO_ASSET_KEY = "videosamples/examples/bipbop_16x9/bipbop_16x9_variant.m3u8"
DEMO_DURATION_SECONDS = 596  # ~10 минут
DEMO_QUALITIES = ["auto", "1080p", "720p", "480p"]

# Количество сезонов и серий для сериалов
SERIES_SEASONS = 2
SERIES_EPISODES_PER_SEASON = 3
SERIES_EPISODE_DURATION = 2400  # ~40 минут


class Command(BaseCommand):
    help = "Создаёт демо-видеоресурсы для фильмов и сериалов. Идемпотентна."

    @transaction.atomic
    def handle(self, *args, **options):
        titles = Title.objects.published()
        if not titles.exists():
            raise CommandError("Нет опубликованных записей. Сначала запустите ensure_demo_data.")

        movies_created = 0
        series_created = 0

        for title in titles:
            if title.type == Title.Type.MOVIE:
                movies_created += self._ensure_movie_asset(title)
            elif title.type == Title.Type.SERIES:
                series_created += self._ensure_series_assets(title)

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово. Фильмы: {movies_created} новых VideoAsset, "
                f"Сериалы: {series_created} новых эпизодов."
            )
        )

    def _ensure_movie_asset(self, title):
        """Создаёт VideoAsset для фильма, если его ещё нет."""
        if VideoAsset.objects.filter(title=title).exists():
            return 0

        duration = (title.duration_minutes * 60) if title.duration_minutes else DEMO_DURATION_SECONDS

        VideoAsset.objects.create(
            title=title,
            provider=VideoAsset.Provider.CLOUDFLARE_STREAM,
            stream_type=VideoAsset.StreamType.HLS,
            asset_key=DEMO_ASSET_KEY,
            duration_seconds=duration,
            available_qualities=DEMO_QUALITIES,
            status=VideoAsset.Status.READY,
            access_level=VideoAsset.AccessLevel.FREE,
        )
        self.stdout.write(f"  + VideoAsset для фильма «{title.name}»")
        return 1

    def _ensure_series_assets(self, title):
        """Создаёт сезоны, серии и VideoAsset для сериала."""
        created = 0

        for season_num in range(1, SERIES_SEASONS + 1):
            season, _ = Season.objects.get_or_create(
                title=title,
                number=season_num,
                defaults={
                    "name": f"Сезон {season_num}",
                    "release_year": title.release_year + season_num - 1,
                },
            )

            for ep_num in range(1, SERIES_EPISODES_PER_SEASON + 1):
                episode, was_created = Episode.objects.get_or_create(
                    season=season,
                    number=ep_num,
                    defaults={
                        "name": f"Серия {ep_num}",
                        "duration_seconds": SERIES_EPISODE_DURATION,
                    },
                )

                if not VideoAsset.objects.filter(episode=episode).exists():
                    VideoAsset.objects.create(
                        episode=episode,
                        provider=VideoAsset.Provider.CLOUDFLARE_STREAM,
                        stream_type=VideoAsset.StreamType.HLS,
                        asset_key=DEMO_ASSET_KEY,
                        duration_seconds=SERIES_EPISODE_DURATION,
                        available_qualities=DEMO_QUALITIES,
                        status=VideoAsset.Status.READY,
                        access_level=VideoAsset.AccessLevel.FREE,
                    )
                    created += 1

        if created:
            self.stdout.write(f"  + {created} эпизодов для сериала «{title.name}»")
        return created
