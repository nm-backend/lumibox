"""
Перенос источников видео в PlaybackSource.

До этой миграции источник описывался тремя способами: файл серии
(Episode.file), альтернативный плеер (Title.player_url_2) и подпись
озвучки (Title.voice_acting). Здесь всё это становится строками одной
таблицы, после чего старые поля удаляются следующей миграцией.

Файлы на диске не трогаем: FileField хранит путь строкой, поэтому
достаточно перенести само значение.
"""

from django.db import migrations
from django.utils.text import slugify

# Подписи озвучек берём константами, а не из модели: миграция обязана
# работать одинаково и через год, когда список choices уже поменяется.
VOICE_LABELS = {
    "dubbed": "Дублированный (Лицензия)",
    "lostfilm": "LostFilm",
    "hdrezka": "HDRezka Studio",
    "newstudio": "NewStudio",
    "original": "Оригинал (Eng.)",
    "subtitles": "Субтитры",
    "multivoice": "Многоголосый",
}


def _voice_slug(raw, taken):
    """Латинский адрес для озвучки. Кириллица через slugify даёт пустоту."""
    slug = raw if raw in VOICE_LABELS else slugify(raw, allow_unicode=False)
    if not slug:
        slug = "voice"
    candidate, number = slug, 2
    while candidate in taken:
        candidate = f"{slug}-{number}"
        number += 1
    taken.add(candidate)
    return candidate


def forwards(apps, schema_editor):
    Title = apps.get_model("catalog", "Title")
    Episode = apps.get_model("catalog", "Episode")
    VoiceOver = apps.get_model("catalog", "VoiceOver")
    PlaybackSource = apps.get_model("catalog", "PlaybackSource")

    # 1. Справочник озвучек — из значений, которые редакторы уже проставили.
    raw_values = (
        Title.objects.exclude(voice_acting="")
        .values_list("voice_acting", flat=True)
        .distinct()
    )
    taken_slugs = set(VoiceOver.objects.values_list("slug", flat=True))
    voice_by_value = {}
    for raw in raw_values:
        name = VOICE_LABELS.get(raw, raw)
        existing = VoiceOver.objects.filter(name=name).first()
        if existing is None:
            existing = VoiceOver.objects.create(name=name, slug=_voice_slug(raw, taken_slugs))
        voice_by_value[raw] = existing

    # 2. Файлы серий. Озвучку берём с записи: до сих пор она была одна на всё.
    sources = []
    for episode in Episode.objects.exclude(file="").select_related("title"):
        sources.append(
            PlaybackSource(
                title_id=episode.title_id,
                episode_id=episode.pk,
                voice=voice_by_value.get(episode.title.voice_acting),
                kind="file",
                file=episode.file.name,
                quality=episode.title.quality or "",
                order=0,
            )
        )

    # 3. Альтернативный плеер записи. Серия не указана: ссылка вела на запись
    #    целиком, а не на конкретную серию.
    for title in Title.objects.exclude(player_url_2=""):
        sources.append(
            PlaybackSource(
                title_id=title.pk,
                episode_id=None,
                voice=None,
                kind="embed",
                url=title.player_url_2,
                quality=title.quality or "",
                order=10,
            )
        )

    PlaybackSource.objects.bulk_create(sources, batch_size=500)


def backwards(apps, schema_editor):
    """Возврат: чистим перенесённое, исходные поля ещё на месте."""
    apps.get_model("catalog", "PlaybackSource").objects.all().delete()
    apps.get_model("catalog", "VoiceOver").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("catalog", "0013_playback_sources")]

    operations = [migrations.RunPython(forwards, backwards)]
