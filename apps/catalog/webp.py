"""WebP-копии изображений при загрузке.

При сохранении Title, Frame, Collection и других моделей с картинками
рядом с оригиналом кладётся WebP-копия: она весит втрое меньше JPEG при
той же видимой чёткости. Оригинал остаётся — шаблон выбирает копию через
фильтр webp_url, а браузеры без поддержки WebP получают исходник.

Работа идёт через API хранилища, а не через путь на диске. Раньше здесь
стояла проверка «локальное ли хранилище», и при Cloudflare R2 конвертация
пропускалась целиком: в продакшене копий не появлялось вовсе, фильтр молча
отдавал оригиналы, и весь механизм простаивал ровно там, где экономия
трафика нужнее всего. Комментарий обещал, что «сжатием займётся CDN», —
но CDN отдаёт то, что в бакете, и сам ничего не пересжимает.

Подключается в apps.py приложения catalog через ready().
"""

from __future__ import annotations

import io
import logging
import os

from django.core.files.base import ContentFile
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger("apps.catalog.webp")

# Поля с изображениями, которые стоит конвертировать в WebP.
# Ключ — модель в формате app_label.ModelName, значение — список полей.
IMAGE_FIELDS_BY_MODEL: dict[str, list[str]] = {
    "catalog.Title": ["poster", "backdrop", "logo"],
    "catalog.Frame": ["image"],
    "catalog.Collection": ["cover"],
    "catalog.Person": ["photo"],
    "catalog.Studio": ["logo"],
    "catalog.Award": ["logo"],
    "users.User": ["avatar"],
}

# Форматы, которые есть смысл пересжимать. GIF пропускаем: анимация
# в WebP теряется, а статичный кадр вместо неё — это уже не та картинка.
CONVERTIBLE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def webp_name(name: str) -> str:
    """Имя WebP-копии рядом с оригиналом: posters/a.jpg → posters/a.webp."""
    base, _ = os.path.splitext(name)
    return f"{base}.webp"


def convert_field(field) -> str | None:
    """
    Делает WebP-копию файла из поля и возвращает её имя.

    Читает и пишет через хранилище: то же самое работает и на диске,
    и в бакете. Возвращает None, если копия не нужна или не получилась —
    вызывающая сторона на это не смотрит, потому что отсутствие копии
    не ошибка: шаблон просто отдаст оригинал.
    """
    from PIL import Image

    name = getattr(field, "name", "")
    if not name:
        return None

    suffix = os.path.splitext(name)[1].lower()
    if suffix not in CONVERTIBLE_SUFFIXES:
        return None

    storage = field.storage
    target = webp_name(name)

    # Уже сделана — второй раз не платим ни за чтение, ни за выгрузку.
    try:
        if storage.exists(target):
            return target
    except Exception:
        logger.exception("WebP: не удалось проверить наличие копии %s", target)
        return None

    try:
        with storage.open(name, "rb") as source:
            image: Image.Image = Image.open(source)
            # Пиксели читаем до закрытия файла: PIL по умолчанию ленив,
            # и после выхода из with картинка окажется без данных.
            image.load()
            if image.mode in ("P", "LA"):
                image = image.convert("RGBA")

            buffer = io.BytesIO()
            image.save(buffer, "WEBP", quality=85, method=6, lossless=False)

        storage.save(target, ContentFile(buffer.getvalue()))
        logger.debug("WebP создан: %s", target)
        return target
    except Exception:
        logger.exception("WebP: ошибка конвертации %s", name)
        return None


@receiver(post_save)
def convert_images_to_webp(sender, instance, **kwargs) -> None:
    """
    Сигнал post_save любой модели: делает WebP-копии её изображений.

    Срабатывает на все модели и быстро выходит для тех, что не в списке.
    Конвертация синхронная: она идёт следом за загрузкой оригинала, которую
    редактор уже дождался, и занимает тот же порядок времени. Выносить её
    в очередь пришлось бы ценой того, что без запущенного Celery копии
    не появлялись бы вовсе — а Redis в этом проекте необязателен.
    """
    model_key = f"{sender._meta.app_label}.{sender.__name__}"
    fields = IMAGE_FIELDS_BY_MODEL.get(model_key)
    if not fields:
        return

    for field_name in fields:
        field = getattr(instance, field_name, None)
        if not field or not field.name:
            continue
        convert_field(field)
