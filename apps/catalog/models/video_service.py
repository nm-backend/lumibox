"""
Служебные модели интеграции с внешним видеосервисом.
"""

from django.db import models


class VideoServiceSyncState(models.Model):
    """
    Когда в последний раз прошла синхронизация каталога с видеосервисом.

    Одна строка с постоянным ключом: команда sync_video_service читает
    отсюда `last_updated_from` и передаёт его в API параметром
    `updated_from`, чтобы тянуть только видео, изменённые после
    прошлого запуска.
    """

    key = models.CharField(max_length=16, unique=True, default="default")
    last_updated_from = models.DateTimeField(
        "Синхронизировано по",
        null=True,
        blank=True,
        help_text="Значение параметра updated_from для следующего запуска.",
    )
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Состояние синхронизации видеосервиса"
        verbose_name_plural = "Состояния синхронизации видеосервиса"

    def __str__(self):
        return self.key

    @classmethod
    def get_solo(cls):
        """Единственная строка состояния (создаётся при первом обращении)."""
        obj, _ = cls.objects.get_or_create(key="default")
        return obj
