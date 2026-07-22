from django.db import models

from apps.core.validators import validate_image_file


class Frame(models.Model):
    """
    Кадр из фильма для галереи на странице.

    Отдельная модель, а не несколько полей у Title: кадров может быть
    сколько угодно, и добавление шестого не должно требовать миграции.

    TimeStampedModel здесь не нужна: это медиа-вложение, дата его
    добавления никого не интересует.
    """

    title = models.ForeignKey(
        "catalog.Title",
        verbose_name="Фильм или сериал",
        on_delete=models.CASCADE,
        related_name="frames",
    )
    image = models.ImageField(
        "Кадр",
        upload_to="frames/%Y/%m",
        validators=[validate_image_file],
        help_text="Горизонтальный кадр, до 5 МБ",
    )
    caption = models.CharField(
        "Подпись",
        max_length=200,
        blank=True,
        help_text="Необязательно. Используется как alt-текст для незрячих.",
    )
    # Порядок задаёт редактор: кадры рассказывают историю, а не сортируются
    # по дате загрузки.
    order = models.PositiveSmallIntegerField("Порядок", default=100)

    class Meta:
        verbose_name = "Кадр"
        verbose_name_plural = "Кадры"
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["title", "order"], name="frame_title_order_idx"),
        ]

    def __str__(self):
        return self.caption or f"Кадр из «{self.title.name}»"
