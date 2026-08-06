"""
Валидаторы видеофайлов.

FileExtensionValidator смотрит только на имя файла: в MEDIA можно
положить любой мусор с расширением .mp4 — сайт будет отдавать его
как видео. Здесь читаются первые байты файла и сверяются с сигнатурой
контейнера, плюс есть санитарный лимит размера (не вместо серверных
ограничений на размер запроса, а как защита от очевидной ошибки).
"""

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

# Сигнатуры контейнеров, которые заявляет FileExtensionValidator.
# mp4 начинается с бокса ftyp (обычно с 4-го байта), поэтому ищем его
# в пределах окна; webm/mkv и ogg начинаются строго с магической
# последовательности с первого байта.
VIDEO_SIGNATURES = {
    "mp4": (b"ftyp", 64),
    "webm": (b"\x1a\x45\xdf\xa3", 8),
    "ogg": (b"OggS", 8),
}

# Санитарный потолок: серия в 4 ГБ — уже признак ошибки редактора.
MAX_VIDEO_BYTES = 4 * 1024**3


def validate_video_signature(value):
    """Проверяет, что содержимое файла соответствует заявленному расширению."""
    ext = value.name.rsplit(".", 1)[-1].lower() if "." in value.name else ""
    if ext not in VIDEO_SIGNATURES:
        return
    marker, window = VIDEO_SIGNATURES[ext]
    try:
        value.seek(0)
        head = value.read(window)
        value.seek(0)
    except (AttributeError, OSError):
        # Нечитаемый поток (например, удалённый файл в сторадже) —
        # не наше дело, это поймает само сохранение файла.
        return
    if marker not in head:
        raise ValidationError(
            _("Файл не похож на видео: содержимое не соответствует расширению .%(ext)s."),
            params={"ext": ext},
            code="video_signature",
        )


def validate_video_size(value):
    """Отклоняет файлы явно нереального размера."""
    if getattr(value, "size", 0) > MAX_VIDEO_BYTES:
        raise ValidationError(
            _("Видеофайл больше 4 ГБ — проверьте, что вы загружаете именно видео."),
            code="video_too_large",
        )
