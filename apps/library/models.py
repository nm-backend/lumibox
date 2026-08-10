from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.library.managers import UserTitleRelationQuerySet


class UserTitleRelation(TimeStampedModel):
    """
    Общая основа для связей «пользователь — запись каталога».

    И избранное, и история устроены одинаково: кто, что и когда.
    Описываем это один раз. Модель абстрактная, своей таблицы нет.

    Ссылаемся на settings.AUTH_USER_MODEL, а не импортируем User напрямую:
    так приложение не сломается, если модель пользователя когда-нибудь заменят.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        on_delete=models.CASCADE,
    )
    title = models.ForeignKey(
        "catalog.Title",
        verbose_name="Фильм или сериал",
        on_delete=models.CASCADE,
    )

    # Менеджер наследуется обоими потомками. Миграции он не порождает:
    # менеджер — это код, а не структура таблицы.
    objects = UserTitleRelationQuerySet.as_manager()

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.user} — {self.title}"


class Favorite(UserTitleRelation):
    """Запись в избранном."""

    class Meta:
        verbose_name = "Избранное"
        verbose_name_plural = "Избранное"
        ordering = ["-created_at"]
        constraints = [
            # База сама не даст добавить один фильм в избранное дважды.
            # Проверки в коде мало: два одновременных запроса обойдут её.
            models.UniqueConstraint(fields=["user", "title"], name="unique_favorite"),
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="favorite_user_date_idx"),
        ]


class WatchHistory(UserTitleRelation):
    """
    Запись в истории просмотров.

    Пользователь может открывать страницу много раз, но в истории
    остаётся одна запись — обновляется время последнего просмотра.
    Поле episode — последняя серия, с которой начали смотреть: из него
    карточка каталога показывает бейдж «Продолжить с S1E3».
    """

    watched_at = models.DateTimeField("Последний просмотр", auto_now=True)
    episode = models.ForeignKey(
        "catalog.Episode",
        verbose_name="Последняя серия",
        related_name="progress_entries",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Серия, с которой пользователь начал смотреть. Пусто — страницу только открывали.",
    )

    # Позиция внутри видео. Без неё «продолжить просмотр» открывало серию
    # с нуля: мы знали, ЧТО человек смотрел, но не знали, где остановился.
    # Секунды целым числом — доли секунды в интерфейсе не нужны.
    position_seconds = models.PositiveIntegerField(
        "Позиция, сек",
        default=0,
    )
    duration_seconds = models.PositiveIntegerField(
        "Длительность, сек",
        null=True,
        blank=True,
        help_text="Приходит от плеера. Нужна, чтобы отличить досмотренное от брошенного.",
    )

    class Meta:
        verbose_name = "История просмотров"
        verbose_name_plural = "История просмотров"
        ordering = ["-watched_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "title"], name="unique_watch_history"),
        ]
        indexes = [
            models.Index(fields=["user", "-watched_at"], name="history_user_date_idx"),
            # Тренды главной фильтруют по времени без пользователя
            # (get_trending_titles: watched_at__gte=неделя назад) — этот
            # запрос должен идти по индексу, а не сканировать всю таблицу.
            models.Index(fields=["-watched_at"], name="history_watched_at_idx"),
        ]


class Watchlist(UserTitleRelation):
    """Запись в списке «Смотреть позже»."""

    class Meta:
        verbose_name = "Смотреть позже"
        verbose_name_plural = "Смотреть позже"
        ordering = ["-created_at"]
        constraints = [
            # Те же гарантии, что и у избранного: база не даст продублировать
            # запись, даже если два запроса придут одновременно.
            models.UniqueConstraint(fields=["user", "title"], name="unique_watchlist"),
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="watchlist_user_date_idx"),
        ]
