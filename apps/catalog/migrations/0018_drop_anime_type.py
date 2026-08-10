"""
Убирает тип «Аниме» из каталога.

Сначала переводим уже существующие записи, потом сужаем список выбора.
Порядок важен: если сначала убрать вариант, записи со старым значением
останутся в базе, но перестанут проходить валидацию — админка на них
начнёт ругаться, а get_type_display() покажет сырое «anime».

В мультфильмы, а не в сериалы: это ближайший по смыслу раздел, и зритель,
пришедший по старой ссылке, попадёт туда, где такому фильму и место.
"""

from django.db import migrations, models


def anime_to_cartoon(apps, schema_editor):
    apps.get_model("catalog", "Title").objects.filter(type="anime").update(type="cartoon")


def noop(apps, schema_editor):
    """Обратно не переводим: какие из мультфильмов были аниме — уже неизвестно."""


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0017_franchise'),
    ]

    operations = [
        migrations.RunPython(anime_to_cartoon, noop),
        migrations.AlterField(
            model_name='title',
            name='type',
            field=models.CharField(choices=[('movie', 'Фильм'), ('series', 'Сериал'), ('cartoon', 'Мультфильм'), ('tv_show', 'ТВ-шоу')], default='movie', max_length=10, verbose_name='Тип'),
        ),
    ]
