"""Массовый импорт каталога Vibix: уникальность kp_id и внешние адреса картинок.

- poster_url/backdrop_url у Title: адреса постера и фона из каталога
  видеосервиса. Картинки не скачиваются (чужой трафик/права), но адрес
  сохраняется, чтобы будущая загрузка не требовала повторного обхода API.
- locked_at у VideoServiceSyncState: отметка захвата длительной операции,
  защита от параллельных прогонов массового импорта.
- Частичный уникальный индекс по kp_id: дубль невозможен на уровне БД даже
  при гонке двух процессов. Перед созданием индекса дубликаты очищаются —
  остаётся самая ранняя запись, у остальных kp_id сбрасывается в пустую
  строку (данные не удаляются, записи не трогаются иначе).
"""

from django.db import migrations, models
from django.db.models import Count, Q


def dedupe_kp_ids(apps, schema_editor):
    """Оставляет за каждым непустым kp_id самую раннюю запись."""
    Title = apps.get_model("catalog", "Title")

    duplicates = (
        Title.objects.exclude(kp_id="")
        .values("kp_id")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    for row in duplicates.iterator():
        for extra in Title.objects.filter(kp_id=row["kp_id"]).order_by("pk")[1:]:
            Title.objects.filter(pk=extra.pk).update(kp_id="")


def restore_kp_ids(apps, schema_editor):
    """Обратной дороги нет: затёртые дубликаты неотличимы от пустых полей."""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0025_enable_vibix_demo"),
    ]

    operations = [
        migrations.AddField(
            model_name="title",
            name="poster_url",
            field=models.URLField(
                blank=True,
                help_text="Ссылка на постер в каталоге видеосервиса. Заполняется синхронизацией.",
                max_length=500,
                verbose_name="Адрес постера (внешний)",
            ),
        ),
        migrations.AddField(
            model_name="title",
            name="backdrop_url",
            field=models.URLField(
                blank=True,
                help_text="Ссылка на широкоформатный постер в каталоге видеосервиса.",
                max_length=500,
                verbose_name="Адрес фона (внешний)",
            ),
        ),
        migrations.AddField(
            model_name="videoservicesyncstate",
            name="locked_at",
            field=models.DateTimeField(
                blank=True,
                help_text=(
                    "Отметка захвата длительной операции (массовый импорт). "
                    "Не пустая — второй запуск отклоняется до снятия блокировки."
                ),
                null=True,
                verbose_name="Заблокировано до",
            ),
        ),
        migrations.RunPython(dedupe_kp_ids, restore_kp_ids),
        migrations.AddConstraint(
            model_name="title",
            constraint=models.UniqueConstraint(
                condition=~Q(kp_id=""),
                fields=["kp_id"],
                name="title_kp_id_uniq_when_filled",
            ),
        ),
    ]
