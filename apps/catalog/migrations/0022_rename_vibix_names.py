"""
Переименование интеграции с внешним видеосервисом.

Модель VideoServiceSyncState раньше называлась VibixSyncState, поля
Title.vibix_id/vibix_type — Title.player_id/player_type. Переименования
не меняют схему, но должны быть отдельной миграцией: предыдущие
(0020, 0021) уже применены, и править их задним числом нельзя.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    """RenameModel + RenameField + приведение verbose_name/help_text к модели."""

    dependencies = [
        ("catalog", "0021_title_vibix_id_title_vibix_type"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="VibixSyncState",
            new_name="VideoServiceSyncState",
        ),
        migrations.RenameField(
            model_name="title",
            old_name="vibix_id",
            new_name="player_id",
        ),
        migrations.RenameField(
            model_name="title",
            old_name="vibix_type",
            new_name="player_type",
        ),
        migrations.AlterModelOptions(
            name="videoservicesyncstate",
            options={
                "verbose_name": "Состояние синхронизации видеосервиса",
                "verbose_name_plural": "Состояния синхронизации видеосервиса",
            },
        ),
        migrations.AlterField(
            model_name="title",
            name="kp_id",
            field=models.CharField(
                blank=True,
                help_text="Например 326. Если заполнен — внешний плеер покажет фильм по этому ID.",
                max_length=20,
                verbose_name="ID на Кинопоиске",
            ),
        ),
        migrations.AlterField(
            model_name="title",
            name="imdb_id",
            field=models.CharField(
                blank=True,
                help_text="Например tt0111161. Используется, когда ID Кинопоиска не задан.",
                max_length=20,
                verbose_name="ID на IMDb",
            ),
        ),
        migrations.AlterField(
            model_name="title",
            name="player_id",
            field=models.CharField(
                blank=True,
                help_text="Внутренний ID видео внешнего плеера (data-id из embed_code API).",
                max_length=20,
                verbose_name="ID видео в плеере",
            ),
        ),
        migrations.AlterField(
            model_name="title",
            name="player_type",
            field=models.CharField(
                blank=True,
                help_text="Тип эмбеда: movie или serial (data-type из embed_code API).",
                max_length=10,
                verbose_name="Тип видео в плеере",
            ),
        ),
    ]
