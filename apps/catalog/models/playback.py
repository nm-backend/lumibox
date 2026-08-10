from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models

from apps.catalog.validators import validate_video_signature, validate_video_size


class PlaybackSource(models.Model):
    """
    Один источник видео: конкретный файл или внешний плеер.

    Раньше источник описывался тремя несовместимыми способами: файл лежал
    в Episode.file, альтернативный плеер — в Title.player_url_2, а озвучка
    была просто подписью в Title.voice_acting. Выбрать озвучку зритель
    не мог вовсе, а шаблон и скрипт знали про каждый способ отдельно.

    Здесь всё сведено в одну таблицу:
    - у фильма источники висят прямо на записи (episode пустой);
    - у сериала — на конкретной серии;
    - у одной серии их столько, сколько озвучек залил редактор.

    Порядок показа задаёт order: первый источник открывается по умолчанию.
    Отдельного флага «основной» нет намеренно — два поля рассинхронизируются,
    а одно упорядочивание не может.
    """

    class Kind(models.TextChoices):
        FILE = "file", "Видеофайл"
        EMBED = "embed", "Внешний плеер"

    title = models.ForeignKey(
        "catalog.Title",
        verbose_name="Фильм или сериал",
        on_delete=models.CASCADE,
        related_name="playback_sources",
    )
    episode = models.ForeignKey(
        "catalog.Episode",
        verbose_name="Серия",
        on_delete=models.CASCADE,
        related_name="playback_sources",
        null=True,
        blank=True,
        help_text="Пусто — источник фильма целиком. Для сериала укажите серию.",
    )
    voice = models.ForeignKey(
        "catalog.VoiceOver",
        verbose_name="Озвучка",
        on_delete=models.SET_NULL,
        related_name="sources",
        null=True,
        blank=True,
        help_text="Пусто — единственная озвучка, выбор в плеере не покажем.",
    )

    kind = models.CharField(
        "Тип источника",
        max_length=10,
        choices=Kind.choices,
        default=Kind.FILE,
    )
    file = models.FileField(
        "Видеофайл",
        upload_to="episodes/%Y/%m",
        blank=True,
        validators=[
            FileExtensionValidator(["mp4", "webm", "ogg"]),
            validate_video_signature,
            validate_video_size,
        ],
        help_text="Для типа «Видеофайл». mp4, webm или ogg.",
    )
    url = models.URLField(
        "Ссылка на плеер",
        blank=True,
        help_text="Для типа «Внешний плеер». Хост должен быть из списка доверенных.",
    )

    quality = models.CharField(
        "Качество",
        max_length=10,
        blank=True,
        help_text="Например: WEB-DL, BDRip. Показывается рядом с выбором озвучки.",
    )
    order = models.PositiveSmallIntegerField(
        "Порядок",
        default=100,
        help_text="Меньше — выше в списке. Первый источник открывается сразу.",
    )

    class Meta:
        verbose_name = "Источник видео"
        verbose_name_plural = "Источники видео"
        ordering = ["order", "id"]
        indexes = [
            # Страница записи забирает источники серии одним запросом.
            models.Index(fields=["title", "episode", "order"], name="playback_title_ep_idx"),
        ]

    def __str__(self):
        parts = [self.get_kind_display()]
        if self.episode_id:
            parts.append(str(self.episode))
        if self.voice_id:
            parts.append(str(self.voice))
        return " · ".join(parts)

    def clean(self):
        """
        Тип источника определяет, какое поле обязано быть заполнено.

        Внешнюю ссылку дополнительно проверяем по белому списку хостов:
        без этого редактор вставил бы во фрейм произвольный адрес, а вместе
        с ним — чужой скрипт на странице своего сайта.
        """
        super().clean()

        if self.kind == self.Kind.FILE:
            if not self.file:
                raise ValidationError({"file": "Для видеофайла загрузите файл."})
            if self.url:
                raise ValidationError({"url": "У видеофайла ссылки быть не должно."})
            return

        if not self.url:
            raise ValidationError({"url": "Для внешнего плеера укажите ссылку."})
        if self.file:
            raise ValidationError({"file": "У внешнего плеера файла быть не должно."})

        from apps.catalog.embeds import get_embed_url

        if get_embed_url(self.url) is None:
            raise ValidationError(
                {"url": "Этот хост не в списке доверенных — вставить его в плеер нельзя."}
            )

    @property
    def src(self):
        """Адрес для плеера: файл отдаём напрямую, ссылку — во встраиваемом виде."""
        if self.kind == self.Kind.FILE:
            return self.file.url if self.file else ""

        from apps.catalog.embeds import get_embed_url

        return get_embed_url(self.url) or ""
