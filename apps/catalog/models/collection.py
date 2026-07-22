from django.db import models
from django.urls import reverse

from apps.core.models import SeoModel, TimeStampedModel
from apps.core.validators import validate_image_file


class CollectionQuerySet(models.QuerySet):
    def published(self):
        # Получаем только опубликованные подборки
        return self.filter(is_published=True)

    def featured(self):
        return self.published().filter(is_featured=True)


class Collection(SeoModel, TimeStampedModel):
    """
    Тематическая подборка: «Лучшее за год», «Фильмы про космос».

    Порядок записей внутри подборки задаёт редактор, поэтому связь
    идёт через промежуточную модель CollectionItem с полем order.
    Обычный ManyToManyField такого не умеет.
    """

    name = models.CharField("Название", max_length=150)
    slug = models.SlugField("Адрес", max_length=170, unique=True)
    description = models.TextField("Описание", blank=True)
    cover = models.ImageField(
        "Обложка",
        upload_to="collections/%Y/%m",
        blank=True,
        validators=[validate_image_file],
        help_text="Горизонтальное изображение, до 5 МБ",
    )

    titles = models.ManyToManyField(
        "catalog.Title",
        verbose_name="Фильмы и сериалы",
        through="catalog.CollectionItem",
        related_name="collections",
        blank=True,
    )

    is_published = models.BooleanField("Опубликована", default=False)
    is_featured = models.BooleanField(
        "Показывать на главной",
        default=False,
        help_text="Подборка появится в отдельном блоке главной страницы",
    )
    # Порядок самих подборок на странице списка.
    order = models.PositiveSmallIntegerField("Порядок", default=100)

    objects = CollectionQuerySet.as_manager()

    class Meta:
        verbose_name = "Подборка"
        verbose_name_plural = "Подборки"
        ordering = ["order", "-created_at"]
        indexes = [
            models.Index(fields=["is_published", "order"], name="collection_pub_order_idx"),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("catalog:collection_detail", kwargs={"slug": self.slug})


class CollectionItem(models.Model):
    """
    Запись внутри подборки.

    Существует только ради поля order: редактор сам решает,
    что показать первым, а не сортировка по алфавиту.
    """

    collection = models.ForeignKey(
        Collection,
        verbose_name="Подборка",
        on_delete=models.CASCADE,
        related_name="items",
    )
    title = models.ForeignKey(
        "catalog.Title",
        verbose_name="Фильм или сериал",
        on_delete=models.CASCADE,
        related_name="collection_items",
    )
    order = models.PositiveSmallIntegerField("Порядок", default=100)

    class Meta:
        verbose_name = "Запись подборки"
        verbose_name_plural = "Записи подборки"
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "title"],
                name="unique_collection_item",
            ),
        ]

    def __str__(self):
        return f"{self.collection.name}: {self.title.name}"
