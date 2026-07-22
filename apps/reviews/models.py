from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import TimeStampedModel

# Шкала оценки. Вынесена в константы, чтобы не писать 1 и 10 в разных местах:
# модель, форма и шаблон должны говорить об одном и том же диапазоне.
MIN_RATING = 1
MAX_RATING = 10


class ReviewQuerySet(models.QuerySet):
    def published(self):
        # Получаем только прошедшие модерацию отзывы
        return self.filter(status=self.model.Status.PUBLISHED)

    def with_author(self):
        # Автор нужен в каждой строке списка — берём его тем же запросом
        return self.select_related("user")


class Review(TimeStampedModel):
    """
    Отзыв с оценкой.

    Один пользователь оставляет один отзыв на одну запись — это
    гарантирует ограничение в базе. Захочет изменить мнение — отредактирует
    существующий отзыв, а не создаст второй.

    Модерация нужна по разделу 5 ТЗ: админ управляет комментариями.
    Новый отзыв публикуется сразу, но админ может его скрыть.
    """

    class Status(models.TextChoices):
        PUBLISHED = "published", "Опубликован"
        HIDDEN = "hidden", "Скрыт"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Автор",
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    title = models.ForeignKey(
        "catalog.Title",
        verbose_name="Фильм или сериал",
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    rating = models.PositiveSmallIntegerField(
        "Оценка",
        validators=[MinValueValidator(MIN_RATING), MaxValueValidator(MAX_RATING)],
        help_text=f"От {MIN_RATING} до {MAX_RATING}",
    )
    text = models.TextField("Отзыв", max_length=2000, blank=True)
    status = models.CharField(
        "Статус",
        max_length=10,
        choices=Status.choices,
        default=Status.PUBLISHED,
    )

    objects = ReviewQuerySet.as_manager()

    class Meta:
        verbose_name = "Отзыв"
        verbose_name_plural = "Отзывы"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "title"], name="unique_review_per_user"),
        ]
        indexes = [
            models.Index(fields=["title", "status"], name="review_title_status_idx"),
        ]

    def __str__(self):
        return f"{self.user} о «{self.title.name}»: {self.rating}"
