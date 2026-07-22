from django.db import models
from django.utils.text import Truncator


class SeoModel(models.Model):
    """
    Поля для поисковой выдачи — раздел 5 ТЗ.

    Оба поля необязательные: если редактор их не заполнил, страница
    возьмёт заголовок и описание из обычных полей. Так каждая страница
    получает осмысленные метатеги без ручной работы над каждой записью.

    Ограничения длины не случайны: поисковики обрезают заголовок
    примерно на 60 символах, описание — примерно на 160.
    """

    meta_title = models.CharField(
        "SEO-заголовок",
        max_length=70,
        blank=True,
        help_text="Если пусто — возьмётся название",
    )
    meta_description = models.CharField(
        "SEO-описание",
        max_length=160,
        blank=True,
        help_text="Если пусто — возьмётся начало описания",
    )

    class Meta:
        abstract = True

    # Наследники переопределяют эти свойства, если запасной вариант другой.
    seo_title_source = "name"
    seo_description_source = "description"

    def get_meta_title(self):
        return self.meta_title or str(getattr(self, self.seo_title_source, ""))

    def get_meta_description(self):
        if self.meta_description:
            return self.meta_description

        source = getattr(self, self.seo_description_source, "") or ""
        return Truncator(source).chars(157)


class TimeStampedModel(models.Model):
    """
    Основа для моделей, которым нужны даты создания и изменения.

    Модель абстрактная: своей таблицы в базе у неё нет. Django просто
    добавит эти два поля в каждую модель-наследника. Так мы описываем
    их один раз вместо копирования в Genre, Country, Title и остальные.

    auto_now_add срабатывает только при создании записи,
    auto_now — при каждом сохранении.
    """

    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    class Meta:
        abstract = True
