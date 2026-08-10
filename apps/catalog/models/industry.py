from django.db import models
from django.urls import reverse

from apps.core.models import SeoModel, TimeStampedModel
from apps.core.validators import validate_image_file


class Franchise(SeoModel, TimeStampedModel):
    """
    Франшиза: серия связанных произведений — все части, спин-оффы, приквелы.

    Отличается от подборки (Collection) тем, что это свойство самого
    произведения, а не редакторская витрина: часть принадлежит франшизе
    всегда, а в подборку её кладут и убирают. Поэтому связь — обычный
    внешний ключ у Title, и блок «Все части» на странице собирается без
    промежуточной таблицы.

    От «Похожих вручную» (Title.related_titles) отличается смыслом:
    похожее — вкусовая рекомендация, франшиза — факт.
    """

    name = models.CharField("Название", max_length=180, unique=True)
    slug = models.SlugField("Адрес", max_length=200, unique=True)
    description = models.TextField("Описание", blank=True)

    class Meta:
        verbose_name = "Франшиза"
        verbose_name_plural = "Франшизы"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("catalog:franchise_detail", kwargs={"slug": self.slug})


class Studio(SeoModel, TimeStampedModel):
    """Студия, лейбл или правообладатель контента в каталоге."""

    name = models.CharField("Название", max_length=180, unique=True)
    slug = models.SlugField("Адрес", max_length=200, unique=True)
    description = models.TextField("Описание", blank=True)
    logo = models.ImageField(
        "Логотип",
        upload_to="studios/%Y/%m",
        blank=True,
        validators=[validate_image_file],
    )
    website = models.URLField("Официальный сайт", blank=True)

    class Meta:
        verbose_name = "Студия"
        verbose_name_plural = "Студии"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("catalog:studio_detail", kwargs={"slug": self.slug})


class Award(SeoModel, TimeStampedModel):
    """Кинопремия с её карточкой и результатами номинаций."""

    name = models.CharField("Название", max_length=180, unique=True)
    slug = models.SlugField("Адрес", max_length=200, unique=True)
    description = models.TextField("Описание", blank=True)
    logo = models.ImageField(
        "Логотип",
        upload_to="awards/%Y/%m",
        blank=True,
        validators=[validate_image_file],
    )
    website = models.URLField("Официальный сайт", blank=True)

    class Meta:
        verbose_name = "Премия"
        verbose_name_plural = "Премии"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("catalog:award_detail", kwargs={"slug": self.slug})


class TitleAward(TimeStampedModel):
    """Номинация или победа произведения либо участника съёмочной группы."""

    class Result(models.TextChoices):
        NOMINEE = "nominee", "Номинация"
        WINNER = "winner", "Победа"

    title = models.ForeignKey(
        "catalog.Title",
        verbose_name="Произведение",
        on_delete=models.CASCADE,
        related_name="award_entries",
    )
    award = models.ForeignKey(
        Award,
        verbose_name="Премия",
        on_delete=models.CASCADE,
        related_name="title_entries",
    )
    person = models.ForeignKey(
        "catalog.Person",
        verbose_name="Персона",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="award_entries",
    )
    year = models.PositiveSmallIntegerField("Год", db_index=True)
    category = models.CharField("Номинация", max_length=180)
    result = models.CharField("Результат", max_length=10, choices=Result.choices, default=Result.NOMINEE)

    class Meta:
        verbose_name = "Награда произведения"
        verbose_name_plural = "Награды произведений"
        ordering = ["-year", "award__name", "category"]
        constraints = [
            models.UniqueConstraint(
                fields=["title", "award", "person", "year", "category"],
                name="unique_title_award_entry",
                # person может быть пустым (награда произведению, а не участнику),
                # а в PostgreSQL два NULL не считаются равными — без этого флага
                # одна и та же награда проходила бы сколько угодно раз.
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["award", "-year"], name="title_award_award_year_idx"),
            models.Index(fields=["title", "-year"], name="title_award_title_year_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.award}: {self.title} — {self.category} ({self.year})"
