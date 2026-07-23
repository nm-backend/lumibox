import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.core.models import TimeStampedModel

STORAGE_KEY_VALIDATOR = RegexValidator(
    regex=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$",
    message="Ключ файла может содержать только латинские буквы, цифры, точки, подчёркивания, дефисы и слеши.",
)


class Season(TimeStampedModel):
    """Сезон сериала с редакционным порядком и самостоятельным описанием."""

    title = models.ForeignKey(
        "catalog.Title",
        verbose_name="Сериал",
        on_delete=models.CASCADE,
        related_name="seasons",
    )
    number = models.PositiveSmallIntegerField("Номер сезона", validators=[MinValueValidator(1)])
    name = models.CharField("Название", max_length=255, blank=True)
    description = models.TextField("Описание", blank=True)
    release_year = models.PositiveSmallIntegerField(
        "Год выпуска",
        null=True,
        blank=True,
        validators=[MinValueValidator(1888), MaxValueValidator(2100)],
    )
    is_published = models.BooleanField("Опубликован", default=True)

    class Meta:
        verbose_name = "Сезон"
        verbose_name_plural = "Сезоны"
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["title", "number"], name="unique_season_number"),
        ]
        indexes = [
            models.Index(fields=["title", "number"], name="season_title_number_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.title} — сезон {self.number}"

    def clean(self) -> None:
        super().clean()
        from apps.catalog.models import Title

        if self.title_id and self.title.type != Title.Type.SERIES:
            raise ValidationError({"title": "Сезон можно создать только для сериала."})

    @property
    def display_name(self) -> str:
        return self.name or f"Сезон {self.number}"


class Episode(TimeStampedModel):
    """Эпизод сериала. Сам медиаресурс хранится отдельно в VideoAsset."""

    season = models.ForeignKey(
        Season,
        verbose_name="Сезон",
        on_delete=models.CASCADE,
        related_name="episodes",
    )
    number = models.PositiveSmallIntegerField("Номер серии", validators=[MinValueValidator(1)])
    name = models.CharField("Название", max_length=255)
    description = models.TextField("Описание", blank=True)
    duration_seconds = models.PositiveIntegerField("Длительность, секунд", null=True, blank=True)
    release_date = models.DateField("Дата выхода", null=True, blank=True)
    intro_start_seconds = models.PositiveIntegerField("Начало заставки, секунд", null=True, blank=True)
    intro_end_seconds = models.PositiveIntegerField("Конец заставки, секунд", null=True, blank=True)
    recap_start_seconds = models.PositiveIntegerField("Начало рекапа, секунд", null=True, blank=True)
    recap_end_seconds = models.PositiveIntegerField("Конец рекапа, секунд", null=True, blank=True)
    is_published = models.BooleanField("Опубликована", default=True)

    class Meta:
        verbose_name = "Серия"
        verbose_name_plural = "Серии"
        ordering = ["season__number", "number"]
        constraints = [
            models.UniqueConstraint(fields=["season", "number"], name="unique_episode_number"),
        ]
        indexes = [
            models.Index(fields=["season", "number"], name="episode_season_number_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.season.title}: {self.season.number} сезон, {self.number} серия"

    def get_absolute_url(self) -> str:
        return reverse(
            "streaming:watch_episode",
            kwargs={
                "slug": self.season.title.slug,
                "season_number": self.season.number,
                "episode_number": self.number,
            },
        )

    def clean(self) -> None:
        super().clean()
        self._validate_marker_pair("intro_start_seconds", "intro_end_seconds", "заставки")
        self._validate_marker_pair("recap_start_seconds", "recap_end_seconds", "рекапа")

    def _validate_marker_pair(self, start_field: str, end_field: str, label: str) -> None:
        start = getattr(self, start_field)
        end = getattr(self, end_field)
        if (start is None) != (end is None):
            raise ValidationError({start_field: f"Укажите и начало, и конец {label}."})
        if start is not None and end is not None and start >= end:
            raise ValidationError({end_field: f"Конец {label} должен быть позже начала."})
        if end is not None and self.duration_seconds and end > self.duration_seconds:
            raise ValidationError({end_field: f"Метка {label} не может выходить за длительность серии."})


class VideoAsset(TimeStampedModel):
    """Лицензированный видеоресурс фильма или эпизода.

    В базе хранится только непрозрачный ключ ресурса. URL доставки формируется
    адаптером разрешённого storage provider, поэтому редактор не может подставить
    сторонний или пиратский источник непосредственно в плеер.
    """

    class Provider(models.TextChoices):
        LOCAL = "local", "Локальное защищённое хранилище"
        CLOUDFLARE_STREAM = "cloudflare_stream", "Cloudflare Stream"
        CLOUDFLARE_R2 = "cloudflare_r2", "Cloudflare R2"
        AWS_S3 = "aws_s3", "AWS S3"
        BACKBLAZE_B2 = "backblaze_b2", "Backblaze B2"
        MINIO = "minio", "MinIO"

    class StreamType(models.TextChoices):
        HLS = "hls", "HLS"
        DASH = "dash", "MPEG-DASH"
        MP4 = "mp4", "MP4"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        READY = "ready", "Готов к показу"
        RETIRED = "retired", "Снят с показа"

    class AccessLevel(models.TextChoices):
        FREE = "free", "Бесплатный"
        PREMIUM = "premium", "Premium"
        VIP = "vip", "VIP"
        RENTAL = "rental", "Аренда"
        PURCHASE = "purchase", "Покупка"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.OneToOneField(
        "catalog.Title",
        verbose_name="Фильм",
        on_delete=models.CASCADE,
        related_name="video_asset",
        null=True,
        blank=True,
    )
    episode = models.OneToOneField(
        Episode,
        verbose_name="Серия",
        on_delete=models.CASCADE,
        related_name="video_asset",
        null=True,
        blank=True,
    )
    provider = models.CharField("Провайдер", max_length=32, choices=Provider.choices, default=Provider.LOCAL)
    stream_type = models.CharField("Формат доставки", max_length=8, choices=StreamType.choices, default=StreamType.MP4)
    asset_key = models.CharField(
        "Ключ ресурса у провайдера",
        max_length=500,
        blank=True,
        validators=[STORAGE_KEY_VALIDATOR],
        help_text="Непрозрачный ключ файла или манифеста без домена и query-параметров.",
    )
    media_file = models.FileField(
        "Локальный видеофайл",
        upload_to="private_media/videos/%Y/%m",
        blank=True,
        validators=[FileExtensionValidator(["mp4", "webm", "m4v", "m3u8", "mpd"])],
    )
    duration_seconds = models.PositiveIntegerField("Длительность, секунд", validators=[MinValueValidator(1)])
    available_qualities = models.JSONField(
        "Доступные качества",
        default=list,
        blank=True,
        help_text='Например: ["auto", "1080p", "720p"]. Для HLS/DASH уровни переключаются адаптером плеера.',
    )
    status = models.CharField("Статус", max_length=10, choices=Status.choices, default=Status.DRAFT)
    access_level = models.CharField(
        "Уровень доступа",
        max_length=10,
        choices=AccessLevel.choices,
        default=AccessLevel.FREE,
    )
    allow_download = models.BooleanField("Разрешить офлайн-загрузку", default=False)
    download_name = models.CharField("Имя скачиваемого файла", max_length=255, blank=True)
    license_ends_at = models.DateTimeField("Лицензия действует до", null=True, blank=True)

    class Meta:
        verbose_name = "Видеоресурс"
        verbose_name_plural = "Видеоресурсы"
        indexes = [
            models.Index(fields=["status", "access_level"], name="asset_status_access_idx"),
            models.Index(fields=["provider", "asset_key"], name="asset_provider_key_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(title__isnull=False, episode__isnull=True)
                | Q(title__isnull=True, episode__isnull=False),
                name="asset_has_exactly_one_content",
            ),
        ]

    def __str__(self) -> str:
        return str(self.content)

    @property
    def content(self):
        return self.episode if self.episode_id else self.title

    @property
    def title_object(self):
        return self.episode.season.title if self.episode_id else self.title

    @property
    def is_available(self) -> bool:
        return self.status == self.Status.READY and (
            self.license_ends_at is None or self.license_ends_at > timezone.now()
        )

    @property
    def display_download_name(self) -> str:
        if self.download_name:
            return self.download_name
        suffix = ".mp4" if self.stream_type == self.StreamType.MP4 else ""
        return f"{self.title_object.slug}{suffix}"

    def clean(self) -> None:
        super().clean()
        errors = {}
        if bool(self.title_id) == bool(self.episode_id):
            errors["title"] = "Выберите ровно один фильм или одну серию."
        if self.title_id:
            from apps.catalog.models import Title

            if self.title.type != Title.Type.MOVIE:
                errors["title"] = "Видеоресурс сериала привязывается к конкретной серии."
        if self.provider == self.Provider.LOCAL and not self.media_file:
            errors["media_file"] = "Для локального провайдера нужен защищённый видеофайл."
        if self.provider != self.Provider.LOCAL and not self.asset_key:
            errors["asset_key"] = "Для внешнего провайдера нужен ключ ресурса."
        if self.media_file and self.provider != self.Provider.LOCAL:
            errors["media_file"] = "Локальный файл можно использовать только с локальным провайдером."
        if not isinstance(self.available_qualities, list) or not all(
            isinstance(quality, str) and quality for quality in self.available_qualities
        ):
            errors["available_qualities"] = "Укажите JSON-массив непустых строк."
        if errors:
            raise ValidationError(errors)


class SubtitleTrack(TimeStampedModel):
    """Субтитры или SDH-дорожка, поставляемые тем же разрешённым провайдером."""

    class Kind(models.TextChoices):
        SUBTITLES = "subtitles", "Субтитры"
        CAPTIONS = "captions", "Субтитры для слабослышащих"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    video_asset = models.ForeignKey(VideoAsset, on_delete=models.CASCADE, related_name="subtitle_tracks")
    language_code = models.CharField("Код языка", max_length=12)
    label = models.CharField("Подпись", max_length=80)
    kind = models.CharField("Тип", max_length=12, choices=Kind.choices, default=Kind.SUBTITLES)
    storage_key = models.CharField("Ключ файла", max_length=500, blank=True, validators=[STORAGE_KEY_VALIDATOR])
    subtitle_file = models.FileField(
        "Локальный файл субтитров",
        upload_to="private_media/subtitles/%Y/%m",
        blank=True,
        validators=[FileExtensionValidator(["vtt", "srt"])],
    )
    is_default = models.BooleanField("Включать по умолчанию", default=False)

    class Meta:
        verbose_name = "Дорожка субтитров"
        verbose_name_plural = "Дорожки субтитров"
        ordering = ["language_code", "label"]
        constraints = [
            models.UniqueConstraint(fields=["video_asset", "language_code", "kind"], name="unique_subtitle_track"),
        ]

    def __str__(self) -> str:
        return f"{self.video_asset}: {self.label}"

    def clean(self) -> None:
        super().clean()
        is_local = self.video_asset_id and self.video_asset.provider == VideoAsset.Provider.LOCAL
        if is_local and not self.subtitle_file:
            raise ValidationError({"subtitle_file": "Для локального провайдера нужен файл субтитров."})
        if not is_local and not self.storage_key:
            raise ValidationError({"storage_key": "Для внешнего провайдера нужен ключ файла субтитров."})


class PlaybackPreference(TimeStampedModel):
    """Персональные настройки воспроизведения, синхронизируемые между устройствами."""

    class Quality(models.TextChoices):
        AUTO = "auto", "Авто"
        UHD = "2160p", "2160p"
        FULL_HD = "1080p", "1080p"
        HD = "720p", "720p"
        SD = "480p", "480p"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="playback_preference")
    autoplay_next = models.BooleanField("Автозапуск следующей серии", default=True)
    default_quality = models.CharField(
        "Качество по умолчанию", max_length=8, choices=Quality.choices, default=Quality.AUTO
    )
    default_speed = models.DecimalField(
        "Скорость по умолчанию",
        max_digits=3,
        decimal_places=2,
        default=1,
        validators=[MinValueValidator(0.5), MaxValueValidator(2)],
    )
    subtitles_language = models.CharField("Предпочтительный язык субтитров", max_length=12, blank=True)

    class Meta:
        verbose_name = "Настройка плеера"
        verbose_name_plural = "Настройки плеера"

    def __str__(self) -> str:
        return f"Настройки плеера: {self.user}"


class WatchProgress(TimeStampedModel):
    """Сохранённая позиция просмотра в конкретном фильме или эпизоде."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="watch_progress")
    video_asset = models.ForeignKey(VideoAsset, on_delete=models.CASCADE, related_name="progress_records")
    position_seconds = models.PositiveIntegerField("Позиция, секунд", default=0)
    duration_seconds = models.PositiveIntegerField("Длительность, секунд", validators=[MinValueValidator(1)])
    is_completed = models.BooleanField("Просмотр завершён", default=False)
    last_watched_at = models.DateTimeField("Последний просмотр", auto_now=True)

    class Meta:
        verbose_name = "Прогресс просмотра"
        verbose_name_plural = "Прогресс просмотра"
        ordering = ["-last_watched_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "video_asset"], name="unique_asset_watch_progress"),
        ]
        indexes = [
            models.Index(fields=["user", "-last_watched_at"], name="progress_user_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.video_asset}: {self.position_seconds} сек."

    @property
    def percentage(self) -> int:
        return min(100, round(self.position_seconds * 100 / self.duration_seconds))
