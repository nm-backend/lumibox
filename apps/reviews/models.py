from django.conf import settings
from django.core.exceptions import ValidationError
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
        # Автор и фильм нужны в каждой строке списка — берём их тем же
        # запросом. Без title здесь список отзывов в API дёргал бы по
        # одному запросу на отзыв (SlugRelatedField читает review.title.slug).
        return self.select_related("user", "title")


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
            # Каталог показывает отзывы только определённого статуса для конкретного фильма.
            models.Index(fields=["title", "status"], name="review_title_status_idx"),
            # Подсчёт рейтинга: SELECT AVG(rating) WHERE title=%s AND status='published'.
            # Покрывающий индекс закрывает и фильтрацию, и агрегацию.
            models.Index(fields=["title", "status", "rating"], name="review_rating_idx"),
        ]

    def __str__(self):
        return f"{self.user} о «{self.title.name}»: {self.rating}"


class CommentQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=self.model.Status.PUBLISHED)

    def roots(self):
        """Только верхний уровень: ответы приходят к ним префетчем."""
        return self.filter(parent__isnull=True)

    def with_author(self):
        # Автор нужен каждой строке ленты; title — сайдбару «Последние
        # комментарии», который ссылается на страницу записи.
        return self.select_related("user", "title")


class Comment(TimeStampedModel):
    """
    Комментарий к записи каталога.

    Отдельная сущность от Review, и это осознанно: Review — это оценка
    (одна на пользователя, 1–10, влияет на рейтинг), а здесь обсуждение,
    где один зритель пишет сколько хочет и отвечает другим.

    Вложенность ровно одна: комментарий и ответы на него. Дерево
    произвольной глубины на кинопортале превращается в нечитаемую лесенку,
    а стоит рекурсивных запросов при выводе. Ограничение проверяет clean().
    """

    class Status(models.TextChoices):
        PUBLISHED = "published", "Опубликован"
        HIDDEN = "hidden", "Скрыт"

    title = models.ForeignKey(
        "catalog.Title",
        verbose_name="Фильм или сериал",
        on_delete=models.CASCADE,
        related_name="comments",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Автор",
        on_delete=models.CASCADE,
        related_name="comments",
    )
    parent = models.ForeignKey(
        "self",
        verbose_name="Ответ на",
        on_delete=models.CASCADE,
        related_name="replies",
        null=True,
        blank=True,
    )
    text = models.TextField("Комментарий", max_length=2000)
    status = models.CharField(
        "Статус",
        max_length=10,
        choices=Status.choices,
        default=Status.PUBLISHED,
    )

    objects = CommentQuerySet.as_manager()

    class Meta:
        verbose_name = "Комментарий"
        verbose_name_plural = "Комментарии"
        ordering = ["created_at"]
        indexes = [
            # Лента записи: только опубликованные, в порядке добавления.
            models.Index(fields=["title", "status", "created_at"], name="comment_title_status_idx"),
            # Сайдбар «Последние комментарии» берёт свежие без привязки к записи.
            models.Index(fields=["-created_at"], name="comment_created_idx"),
        ]

    def __str__(self):
        return f"{self.user} к «{self.title.name}»"

    def clean(self):
        """Ответ на ответ запрещаем: глубина ленты ровно два уровня."""
        super().clean()
        if self.parent_id and self.parent.parent_id:
            raise ValidationError({"parent": "Отвечать можно только на комментарий верхнего уровня."})
