from django.db import models

from apps.core.models import TimeStampedModel


class Reference(TimeStampedModel):
    """
    Общая основа для простых справочников — жанров и стран.

    У них одинаковые поля и одинаковое поведение, поэтому описываем
    это один раз. Модель абстрактная: в базе будут таблицы Genre
    и Country, а таблицы Reference не будет.
    """

    name = models.CharField("Название", max_length=100, unique=True)
    slug = models.SlugField(
        "Адрес",
        max_length=120,
        unique=True,
        help_text="Часть ссылки латиницей, например: dokumentalnyy",
    )

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self):
        return self.name


class Genre(Reference):
    # Meta наследуем, чтобы не повторять ordering.
    # Django сам снимает abstract у наследника, поэтому таблица создастся.
    class Meta(Reference.Meta):
        verbose_name = "Жанр"
        verbose_name_plural = "Жанры"


class Country(Reference):
    class Meta(Reference.Meta):
        verbose_name = "Страна"
        verbose_name_plural = "Страны"
