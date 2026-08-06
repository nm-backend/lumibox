from django.core.validators import FileExtensionValidator
from django.db import models

from apps.catalog.validators import validate_video_signature, validate_video_size


class Episode(models.Model):
    """
    Серия сериала (или отдельная часть фильма) с видеофайлом.

    Отдельная модель, а не поле у Title: серий может быть сколько угодно,
    и добавление десятой не должно требовать миграции. Нумерация задаётся
    парой «сезон + серия», уникальной в пределах одного фильма или сериала.

    Показ на сайте: у Title с эпизодами над вкладками появляется секция
    «Смотреть онлайн» с плеером и списком серий, сгруппированных по сезонам.
    """

    title = models.ForeignKey(
        "catalog.Title",
        verbose_name="Фильм или сериал",
        on_delete=models.CASCADE,
        related_name="episodes",
    )
    season_number = models.PositiveSmallIntegerField(
        "Сезон",
        default=1,
        help_text="Для фильма без сезонов оставьте 1",
    )
    episode_number = models.PositiveSmallIntegerField(
        "Серия",
        help_text="Номер серии внутри сезона",
    )
    name = models.CharField(
        "Название серии",
        max_length=255,
        blank=True,
        help_text="Необязательно, например «Пилот»",
    )
    file = models.FileField(
        "Видеофайл",
        upload_to="episodes/%Y/%m",
        validators=[
            FileExtensionValidator(["mp4", "webm", "ogg"]),
            validate_video_signature,
            validate_video_size,
        ],
        help_text="Видео серии (mp4, webm, ogg)",
    )
    duration_minutes = models.PositiveSmallIntegerField(
        "Длительность, мин",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Серия"
        verbose_name_plural = "Серии"
        ordering = ["season_number", "episode_number", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["title", "season_number", "episode_number"],
                name="episode_title_season_episode_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["title", "season_number"], name="episode_title_season_idx"),
        ]

    def __str__(self):
        label = f"S{self.season_number}E{self.episode_number}"
        if self.name:
            label += f" — {self.name}"
        return f"{label} · {self.title.name}"
