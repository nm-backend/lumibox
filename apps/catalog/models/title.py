from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.catalog.managers import TitleQuerySet
from apps.catalog.models.person import Person
from apps.catalog.models.reference import Country, Genre
from apps.catalog.validators import validate_video_signature, validate_video_size
from apps.catalog.youtube import validate_youtube_url
from apps.core.models import SeoModel, TimeStampedModel
from apps.core.validators import validate_image_file


class Title(SeoModel, TimeStampedModel):
    """
    Фильм или сериал.

    Одна модель на оба типа. У фильма и сериала совпадает почти всё:
    название, описание, постер, год, жанры, страны, возрастной рейтинг.
    Различие описывает поле type.

    Что это даёт: каталог, поиск, фильтры, избранное и история просмотров
    работают с одной сущностью. Будь моделей две, каждую из этих функций
    пришлось бы писать дважды, а «Избранное» пользователя ссылалось бы
    на две разные таблицы.

    Серии живут в отдельной модели Episode со ссылкой на Title
    (related_name="episodes"): у сериала их много, у фильма — ни одной.
    """

    class Type(models.TextChoices):
        MOVIE = "movie", "Фильм"
        SERIES = "series", "Сериал"
        CARTOON = "cartoon", "Мультфильм"
        TV_SHOW = "tv_show", "ТВ-шоу"

    class VoiceActing(models.TextChoices):
        """Типовые варианты озвучки/перевода.

        Значения — те, что привычны зрителю кинопорталов. Поле допускает
        и свободный ввод: редактор может написать название своей студии,
        не входящее в список.
        """

        DUBBED = "dubbed", "Дублированный (Лицензия)"
        LOSTFILM = "lostfilm", "LostFilm"
        HDREZKA = "hdrezka", "HDRezka Studio"
        NEWSTUDIO = "newstudio", "NewStudio"
        ORIGINAL = "original", "Оригинал (Eng.)"
        SUBTITLES = "subtitles", "Субтитры"
        MULTIVOICE = "multivoice", "Многоголосый"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PUBLISHED = "published", "Опубликовано"

    class AgeRating(models.TextChoices):
        EVERYONE = "0+", "0+"
        SIX = "6+", "6+"
        TWELVE = "12+", "12+"
        SIXTEEN = "16+", "16+"
        ADULT = "18+", "18+"

    class Quality(models.TextChoices):
        """Качество видеофайла — то, что видит посетитель в карточке."""

        CAMRIP = "CAMRip", "CAMRip"
        TS = "TS", "TS"
        TC = "TC", "TC"
        HDRIP = "HDRip", "HDRip"
        WEBRIP = "WEBRip", "WEBRip"
        WEB_DL = "WEB-DL", "WEB-DL"
        BDRIP = "BDRip", "BDRip"
        BLURAY = "Blu-ray", "Blu-ray"

    type = models.CharField(
        "Тип",
        max_length=10,
        choices=Type.choices,
        default=Type.MOVIE,
    )
    name = models.CharField("Название", max_length=255)
    original_name = models.CharField(
        "Оригинальное название",
        max_length=255,
        blank=True,
        help_text="Название на языке оригинала",
    )
    slug = models.SlugField(
        "Адрес",
        max_length=280,
        unique=True,
        help_text="Часть ссылки латиницей. В админке заполнится сама.",
    )
    short_description = models.CharField(
        "Короткое описание",
        max_length=200,
        blank=True,
        help_text="Одна фраза для карточки и баннера. Если пусто — возьмётся начало описания.",
    )
    description = models.TextField("Описание", blank=True)

    # 1888 — год самой ранней сохранившейся киносъёмки.
    # Верхняя граница с запасом: каталог хранит и анонсы будущих премьер.
    release_year = models.PositiveSmallIntegerField(
        "Год выпуска",
        validators=[MinValueValidator(1888), MaxValueValidator(2100)],
    )
    release_date = models.DateField(
        "Дата выхода",
        null=True,
        blank=True,
        help_text="Точная дата премьеры, если известна. Год выше обязателен в любом случае.",
    )
    duration_minutes = models.PositiveSmallIntegerField(
        "Длительность, мин",
        null=True,
        blank=True,
        help_text="Для сериала — длительность одной серии",
    )
    quality = models.CharField(
        "Качество",
        max_length=10,
        choices=Quality.choices,
        blank=True,
        help_text="Например: TC, WEB-DL, BDRip. Показывается в карточке каталога.",
    )
    imdb_rating = models.DecimalField(
        "Рейтинг IMDb",
        max_digits=3,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        help_text="Внешний рейтинг для справки, от 0.0 до 10.0",
    )
    kp_rating = models.DecimalField(
        "Рейтинг Кинопоиска",
        max_digits=3,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        help_text="Внешний рейтинг для справки, от 0.0 до 10.0",
    )

    # ID Кинопоиска и IMDb — для внешнего плеера (data-type="kp"/"imdb").
    # Редактору проще найти фильм по известному ID, чем по номеру в каталоге
    # сервиса; сам плеер по ID подтянет контент со своей стороны.
    kp_id = models.CharField(
        "ID на Кинопоиске",
        max_length=20,
        blank=True,
        help_text="Например 326. Если заполнен — внешний плеер покажет фильм по этому ID.",
    )
    imdb_id = models.CharField(
        "ID на IMDb",
        max_length=20,
        blank=True,
        help_text="Например tt0111161. Используется, когда ID Кинопоиска не задан.",
    )

    # Внутренний ID видео во внешнем плеере — значение data-id тега
    # (кнопка «Код» в кабинете видеосервиса даёт ровно такой тег).
    # Синхронизация заполняет его вместе с kp_id/imdb_id; вкладка плеера
    # отдаёт ему предпочтение перед kp/imdb, потому что это официальный
    # формат эмбеда.
    player_id = models.CharField(
        "ID видео в плеере",
        max_length=20,
        blank=True,
        help_text="Внутренний ID видео внешнего плеера (data-id тега плеера).",
    )
    player_type = models.CharField(
        "Тип видео в плеере",
        max_length=10,
        blank=True,
        help_text="Тип эмбеда: movie или series (data-type тега плеера).",
    )
    age_rating = models.CharField(
        "Возрастной рейтинг",
        max_length=3,
        choices=AgeRating.choices,
        blank=True,
    )
    poster = models.ImageField(
        "Постер",
        upload_to="posters/%Y/%m",
        blank=True,
        validators=[validate_image_file],
        help_text="Вертикальное изображение (2:3), до 5 МБ. Обложка карточки в каталоге.",
    )
    backdrop = models.ImageField(
        "Фон страницы",
        upload_to="backdrops/%Y/%m",
        blank=True,
        validators=[validate_image_file],
        help_text="Широкое горизонтальное изображение (16:9) для шапки страницы фильма. Необязательно.",
    )
    logo = models.ImageField(
        "Логотип",
        upload_to="logos/%Y/%m",
        blank=True,
        validators=[validate_image_file],
        help_text="Название фильма картинкой на прозрачном фоне (PNG). Показывается в шапке вместо текста.",
    )

    # Франшиза: «все части» на странице записи. Обычный внешний ключ,
    # а не связь многие-ко-многим: часть принадлежит одной серии фильмов.
    franchise = models.ForeignKey(
        "catalog.Franchise",
        verbose_name="Франшиза",
        on_delete=models.SET_NULL,
        related_name="titles",
        null=True,
        blank=True,
        help_text="Серия связанных фильмов: все части, приквелы, спин-оффы.",
    )

    # Ручные рекомендации: редактор сам решает, что показать рядом.
    # Если не заполнить — страница подберёт похожее по жанрам сама.
    # symmetrical=False: «А похож на Б» не означает обратного.
    related_titles = models.ManyToManyField(
        "self",
        verbose_name="Похожие вручную",
        blank=True,
        symmetrical=False,
        related_name="related_to",
        help_text="Если пусто — похожее подберётся автоматически по совпадению жанров.",
    )

    # Озвучка/перевод — поле выбора с возможностью свободного ввода.
    # Не editable=False: редактор вправе вписать свою студию озвучки.
    voice_acting = models.CharField(
        "Озвучка / Перевод",
        max_length=100,
        choices=VoiceActing.choices,
        blank=True,
        help_text="Как озвучен контент: дубляж, студия или оригинал.",
    )

    # Счётчик просмотров. Держим готовым числом, а не считаем по истории
    # на каждый показ: список «популярное» сортируется по нему без JOIN.
    # Значение растёт через Title.increment_views() — с сессионной защитой
    # от накрутки во вьюхе детальной страницы.
    views_count = models.PositiveIntegerField(
        "Число просмотров",
        default=0,
        editable=False,
    )

    # Второй источник видео жил здесь одним полем player_url_2 и вставлялся
    # в iframe напрямую, минуя белый список хостов. Теперь любые источники —
    # и файлы, и внешние плееры — лежат в PlaybackSource, где адрес обязан
    # пройти embeds.get_embed_url() (см. PlaybackSource.clean).

    # Плашка «10 сезон 5 серия» на карточке сериала — без отдельной модели:
    # редактор пишет строку сам, когда сериал выходит по расписанию.
    latest_episode_info = models.CharField(
        "Последняя серия",
        max_length=120,
        blank=True,
        help_text="Текстовая плашка для сериалов, например: «10 сезон 5 серия».",
    )

    # Трейлер задаётся одним из двух способов, но не обоими сразу — это
    # проверяет clean() ниже. Раздельные поля, а не одно, потому что источники
    # разной природы: внешнюю ссылку встраиваем iframe'ом, свой файл отдаём
    # тегом <video>. Впихнуть оба варианта в одно поле значит гадать по строке.
    #
    # По правилам MVP это YouTube-ссылка (watch, youtu.be или embed):
    # валидатор пропустит только её, а видео ID из ссылки извлекает
    # apps.catalog.youtube, чужой домен в iframe не попадёт.
    trailer_url = models.URLField(
        "Ссылка на трейлер",
        blank=True,
        validators=[validate_youtube_url],
        help_text="YouTube: watch, youtu.be или embed. Оставьте пустым, если загружаете свой видеофайл.",
    )
    trailer_file = models.FileField(
        "Видеофайл трейлера",
        upload_to="trailers/%Y/%m",
        blank=True,
        validators=[
            FileExtensionValidator(["mp4", "webm", "ogg"]),
            validate_video_signature,
            validate_video_size,
        ],
        help_text="Своё видео (mp4, webm, ogg). Оставьте пустым, если указываете ссылку.",
    )

    # Полная версия фильма — отдельное поле от трейлера. Это два разных
    # ролика: трейлер рекламирует фильм, video_url его показывает целиком.
    # Поле валидируется как YouTube-ссылка, в iframe собирается бэкендом
    # из ID ролика (youtube_embed_url) — произвольный адрес не пройдёт.
    video_url = models.URLField(
        "Ссылка на полную версию",
        blank=True,
        validators=[validate_youtube_url],
        help_text="YouTube-ссылка на полный фильм: watch, youtu.be или embed.",
    )

    genres = models.ManyToManyField(
        Genre,
        verbose_name="Жанры",
        related_name="titles",
        blank=True,
    )
    countries = models.ManyToManyField(
        Country,
        verbose_name="Страны",
        related_name="titles",
        blank=True,
    )
    studios = models.ManyToManyField(
        "catalog.Studio",
        verbose_name="Студии",
        related_name="titles",
        blank=True,
    )
    persons = models.ManyToManyField(
        Person,
        verbose_name="Съёмочная группа",
        through="catalog.Participation",
        related_name="titles",
        blank=True,
    )

    # Черновик по умолчанию: новая запись не попадёт на сайт,
    # пока редактор не заполнит её и не опубликует осознанно.
    status = models.CharField(
        "Статус",
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    published_at = models.DateTimeField(
        "Дата публикации",
        null=True,
        blank=True,
        help_text="Проставляется при первой публикации",
    )

    # Рейтинг хранится готовым, а не считается на каждый показ.
    # Причина: средняя оценка через JOIN и GROUP BY на списке из 24 карточек —
    # это то, что кладёт каталог, когда отзывов становится много.
    # Значения пересчитываются при изменении отзыва и раз в час фоновой задачей.
    # editable=False — редактор не должен править их руками.
    rating_average = models.DecimalField(
        "Средняя оценка",
        max_digits=3,
        decimal_places=1,
        null=True,
        blank=True,
        editable=False,
    )
    rating_count = models.PositiveIntegerField(
        "Число оценок",
        default=0,
        editable=False,
    )

    objects = TitleQuerySet.as_manager()

    class Meta:
        verbose_name = "Фильм или сериал"
        verbose_name_plural = "Фильмы и сериалы"
        ordering = ["-release_year", "name", "pk"]
        indexes = [
            # Каталог почти всегда просит «опубликованные фильмы»
            # или «опубликованные сериалы» — этот индекс закрывает оба случая.
            models.Index(fields=["status", "type"], name="title_status_type_idx"),
            # Фильтр и сортировка по годам.
            models.Index(fields=["-release_year"], name="title_year_idx"),
            # Сортировка «новинки»: ORDER BY -published_at LIMIT 12.
            # На прогретом кэше этот индекс не нужен, но первый посетитель
            # после публикации стоит без него скана всей таблицы.
            models.Index(fields=["-published_at"], name="title_published_at_idx"),
            # Сортировка «по рейтингу»: ORDER BY -rating_average, -rating_count.
            # Комбинированный индекс: фильтр по статусу + сортировка.
            models.Index(
                fields=["status", "-rating_average", "-rating_count"],
                name="title_status_rating_idx",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.release_year})"

    def get_absolute_url(self):
        # Ссылку на запись собираем из маршрута, а не пишем «/title/{slug}/»
        # руками: поменяется адрес — шаблоны править не придётся.
        return reverse("catalog:title_detail", kwargs={"slug": self.slug})

    def clean(self):
        # Трейлер — либо ссылка, либо файл, но не оба сразу: иначе непонятно,
        # что показывать посетителю. Ошибка вылезет рядом с формой в админке.
        super().clean()
        if self.trailer_url and self.trailer_file:
            raise ValidationError(
                "Укажите трейлер одним способом: либо ссылкой, либо видеофайлом — не обоими сразу."
            )

    @property
    def trailer_source(self):
        """
        Чем показывать трейлер: 'file' — свой видеофайл, 'url' — внешняя
        ссылка, None — трейлера нет. Оба одновременно исключены в clean().
        """
        if self.trailer_file:
            return "file"
        if self.trailer_url:
            return "url"
        return None

    @property
    def trailer_embed_url(self):
        """
        Встраиваемая ссылка на трейлер или None.

        Собирается только из YouTube-ссылки (плеер MVP открывает YouTube):
        None означает, что введённая ссылка не YouTube, и страница покажет
        обычную кнопку-ссылку наружу вместо встроенного плеера. Чужой
        домен во фрейм не попадёт.
        """
        from apps.catalog.youtube import youtube_embed_url

        return youtube_embed_url(self.trailer_url)

    @property
    def video_embed_url(self):
        """
        Встраиемая ссылка на полную версию фильма или None.

        None — видео на странице не показываем: поле пустое либо ссылка
        не YouTube. Собирается из ID ролика, а не из введённой строки,
        поэтому произвольный iframe-адрес сюда попасть не может.
        """
        from apps.catalog.youtube import youtube_embed_url

        return youtube_embed_url(self.video_url)

    @property
    def has_youtube_video(self):
        """Есть ли полноценный YouTube-плеер: трейлер или полная версия."""
        return bool(self.video_embed_url)

    def save(self, *args, **kwargs):
        # Дату первой публикации проставляем сами, чтобы редактор не мог
        # опубликовать запись и забыть заполнить поле. Условие published_at is None
        # важно: при повторном сохранении дата не должна перезаписываться,
        # иначе старый фильм каждый раз всплывал бы как новинка.
        if self.status == self.Status.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def is_series(self):
        return self.type == self.Type.SERIES

    def increment_views(self):
        """Увеличивает счётчик просмотров на единицу.

        update() вместо save(): не трогаем updated_at и не запускаем
        логику save() — просмотр это событие, а не правка редактора.
        Возвращает новое значение счётчика.
        """
        from django.db.models import F

        Title.objects.filter(pk=self.pk).update(views_count=F("views_count") + 1)
        self.views_count += 1
        return self.views_count
