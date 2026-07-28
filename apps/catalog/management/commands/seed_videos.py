"""
Downloads demo videos (public domain) and creates VideoAsset records
so the "Watch" button works on title pages. Idempotent.

The video is downloaded straight into memory and saved through Django's
default storage backend — whether that's local filesystem or Cloudflare R2.
No temp files are written to disk.
"""

import urllib.request

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Title
from apps.streaming.models import VideoAsset

DEMO_VIDEOS = [
    {
        "title_slug": "nachalo-2010",
        "url": "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_1MB.mp4",
        "filename": "demo-nachalo-2010.mp4",
        "duration": 10,
    },
    {
        "title_slug": "interstellar-2014",
        "url": "https://www.w3schools.com/html/mov_bbb.mp4",
        "filename": "demo-interstellar-2014.mp4",
        "duration": 10,
    },
]

# Провайдер всегда LOCAL, независимо от того, куда default_storage кладёт файл.
#
# «LOCAL» описывает не диск, а способ доставки: ролик отдаётся защищённым
# маршрутом LocalAssetFileView, который читает media_file через тот же
# default_storage. Для файловой системы это чтение с диска, для R2 — чтение
# объекта из бакета; в обоих случаях доступ проверяется до отдачи байтов.
#
# Вариант CLOUDFLARE_R2 здесь не годится: он строит URL из asset_key и
# CLOUDFLARE_R2_DELIVERY_BASE_URL, а команда сохраняет файл в media_file и
# ключа не заполняет. Плеер получал бы PlaybackUnavailable, то есть 404
# на кнопке «Смотреть» ровно там, где хранилище настроено.
_PROVIDER = VideoAsset.Provider.LOCAL


class Command(BaseCommand):
    help = "Downloads demo videos and creates VideoAsset records."

    def handle(self, *args, **options):
        self._download_and_attach()
        self.stdout.write(self.style.SUCCESS("Demo videos ready for playback."))

    def _download_and_attach(self):
        # Step 1: download all videos outside any DB transaction.
        # Network I/O inside a transaction holds the connection open.
        blobs: list[tuple[Title, str, bytes, int]] = []
        for entry in DEMO_VIDEOS:
            try:
                title = Title.objects.get(slug=entry["title_slug"])
            except Title.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f"No title '{entry['title_slug']}' - skipping."
                ))
                continue

            if VideoAsset.objects.filter(
                title=title, status=VideoAsset.Status.READY
            ).exists():
                self.stdout.write(f"  {title.name}: video exists - skipping.")
                continue

            self.stdout.write(f"  Downloading {entry['url']}...")
            req = urllib.request.Request(
                entry["url"],
                headers={"User-Agent": "Mozilla/5.0"},
            )
            # Ролик лежит на чужом сайте, и его недоступность — обычное дело,
            # а не поломка LumiBox. Команда стоит в цепочке запуска контейнера,
            # поэтому необработанное исключение здесь означало бы, что сайт
            # вообще не поднялся из-за демонстрационного видео. Пропускаем
            # запись и продолжаем: каталог важнее ролика.
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read()
            except OSError as error:
                self.stdout.write(self.style.WARNING(
                    f"  Не удалось скачать {entry['url']}: {error}. Пропускаю."
                ))
                continue
            self.stdout.write(f"  -> {len(data)} bytes received")
            blobs.append((title, entry["filename"], data, entry["duration"]))

        if not blobs:
            return

        # Step 2: save to storage inside a fast DB transaction.
        with transaction.atomic():
            for title, filename, data, duration in blobs:
                video_asset = VideoAsset(
                    title=title,
                    provider=_PROVIDER,
                    stream_type=VideoAsset.StreamType.MP4,
                    duration_seconds=duration,
                    status=VideoAsset.Status.READY,
                    access_level=VideoAsset.AccessLevel.FREE,
                    available_qualities=["auto"],
                )
                video_asset.media_file.save(
                    filename,
                    ContentFile(data),
                    save=True,
                )
                self.stdout.write(f"  OK {title.name}: VideoAsset created (id={video_asset.id})")
