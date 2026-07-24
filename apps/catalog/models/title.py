from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.catalog.managers import TitleQuerySet
from apps.catalog.models.person import Person
from apps.catalog.models.reference import Country, Genre
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

    Сезоны и серии появятся отдельной моделью со ссылкой на Title.
    """

    class Type(models.TextChoices):
        MOVIE = "movie", "Фильм"
        SERIES = "series", "Сериал"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PUBLISHED = "published", "Опубликовано"

    class AgeRating(models.TextChoices):
        EVERYONE = "0+", "0+"
        SIX = "6+", "6+"
        TWELVE = "12+", "12+"
        SIXTEEN = "16+", "16+"
        ADULT = "18+", "18+"

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

    # Трейлер задаётся одним из двух способов, но не обоими сразу — это
    # проверяет clean() ниже. Раздельные поля, а не одно, потому что источники
    # разной природы: внешнюю ссылку встраиваем iframe'ом, свой файл отдаём
    # тегом <video>. Впихнуть оба варианта в одно поле значит гадать по строке.
    trailer_url = models.URLField(
        "Ссылка на трейлер",
        blank=True,
        help_text="YouTube, Vimeo, Rutube и т.п. Оставьте пустым, если загружаете свой видеофайл.",
    )
    trailer_file = models.FileField(
        "Видеофайл трейлера",
        upload_to="trailers/%Y/%m",
        blank=True,
        validators=[FileExtensionValidator(["mp4", "webm", "ogg"])],
        help_text="Своё видео (mp4, webm, ogg). Оставьте пустым, если указываете ссылку.",
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
        ordering = ["-release_year", "name"]
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

        None означает «хост незнакомый» — тогда страница покажет обычную
        кнопку-ссылку наружу вместо встроенного плеера. Список доверенных
        хостов живёт в apps.catalog.embeds: пускать во фрейм произвольный
        адрес, введённый редактором, нельзя.
        """
        from apps.catalog.embeds import get_embed_url

        return get_embed_url(self.trailer_url)

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
