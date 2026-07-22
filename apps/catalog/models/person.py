from django.db import models
from django.urls import reverse

from apps.core.models import TimeStampedModel
from apps.core.validators import validate_image_file


class Person(TimeStampedModel):
    """
    Человек из съёмочной группы: актёр, режиссёр, сценарист.

    Одна модель на все профессии. Профессия — это не свойство человека,
    а свойство его участия в конкретном фильме: режиссёр одной картины
    вполне может сыграть роль в другой. Поэтому роль живёт
    в модели Participation, а не здесь.
    """

    name = models.CharField("Имя", max_length=150)
    original_name = models.CharField("Имя в оригинале", max_length=150, blank=True)
    slug = models.SlugField("Адрес", max_length=170, unique=True)
    photo = models.ImageField(
        "Фото",
        upload_to="persons/%Y/%m",
        blank=True,
        validators=[validate_image_file],
    )
    birth_date = models.DateField("Дата рождения", null=True, blank=True)
    biography = models.TextField("Биография", blank=True)

    class Meta:
        verbose_name = "Персона"
        verbose_name_plural = "Персоны"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"], name="person_name_idx"),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("catalog:person_detail", kwargs={"slug": self.slug})

    @property
    def initial(self):
        """Первая буква имени — для заглушки вместо фото."""
        return self.name[:1].upper()


class Participation(models.Model):
    """
    Участие человека в фильме или сериале.

    Промежуточная модель, а не простая связь многие-ко-многим: у участия
    есть свои свойства — роль, имя персонажа и порядок в титрах.
    Без неё нельзя было бы записать, что человек и снял фильм, и сыграл в нём.

    TimeStampedModel здесь не нужна: это техническая связь,
    даты её создания никого не интересуют.
    """

    class Role(models.TextChoices):
        # Порядок объявления — это порядок показа на странице фильма.
        # Сначала режиссёр, потом актёры: так принято в титрах и на афишах.
        DIRECTOR = "director", "Режиссёр"
        ACTOR = "actor", "Актёр"
        WRITER = "writer", "Сценарист"
        PRODUCER = "producer", "Продюсер"
        COMPOSER = "composer", "Композитор"
        OPERATOR = "operator", "Оператор"

    title = models.ForeignKey(
        "catalog.Title",
        verbose_name="Фильм или сериал",
        on_delete=models.CASCADE,
        related_name="participations",
    )
    person = models.ForeignKey(
        Person,
        verbose_name="Персона",
        on_delete=models.CASCADE,
        related_name="participations",
    )
    role = models.CharField("Роль", max_length=20, choices=Role.choices, default=Role.ACTOR)
    character = models.CharField(
        "Имя персонажа",
        max_length=150,
        blank=True,
        help_text="Только для актёров",
    )
    # Порядок в титрах: главные роли должны идти первыми, а не по алфавиту.
    order = models.PositiveSmallIntegerField("Порядок", default=100)

    class Meta:
        verbose_name = "Участие"
        verbose_name_plural = "Участие в проектах"
        ordering = ["order", "person__name"]
        constraints = [
            # Один человек в одном фильме в одной роли — один раз.
            # Сыграть двух персонажей в одном фильме модель пока не позволяет;
            # понадобится — ограничение расширим именем персонажа.
            models.UniqueConstraint(
                fields=["title", "person", "role"],
                name="unique_participation",
            ),
        ]
        indexes = [
            models.Index(fields=["title", "role", "order"], name="participation_title_idx"),
        ]

    def __str__(self):
        if self.character:
            return f"{self.person.name} — {self.character}"
        return f"{self.person.name} ({self.get_role_display()})"
