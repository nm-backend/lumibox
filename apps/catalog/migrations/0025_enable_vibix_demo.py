"""Включает Vibix-плеер для демонстрационного фильма «Начало».

Плееру не нужен API-токен: для data-type="kp" достаточно реального
Kinopoisk ID и publisher ID из окружения. Токен используется только
серверной синхронизацией, которая позднее может заменить kp-режим
внутренним player_id из каталога Vibix.
"""

from django.db import migrations


def enable_vibix_demo(apps, schema_editor):
    Title = apps.get_model("catalog", "Title")
    title = Title.objects.filter(
        slug="nachalo-2010",
        name="Начало",
        release_year=2010,
    ).first()
    if title is None:
        return

    changes = {}
    if not title.kp_id:
        changes["kp_id"] = "447301"
    if not title.imdb_id:
        changes["imdb_id"] = "tt1375666"
    if changes:
        Title.objects.filter(pk=title.pk).update(**changes)


def disable_vibix_demo(apps, schema_editor):
    """Откат убирает только значения, которые добавила эта миграция."""
    Title = apps.get_model("catalog", "Title")
    Title.objects.filter(
        slug="nachalo-2010",
        name="Начало",
        release_year=2010,
        kp_id="447301",
        imdb_id="tt1375666",
    ).update(kp_id="", imdb_id="")


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0024_episode_video_url_title_video_url_and_more"),
    ]

    operations = [
        migrations.RunPython(enable_vibix_demo, disable_vibix_demo),
    ]
