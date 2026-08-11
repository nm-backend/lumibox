"""
Генерация оригинальных постеров-заглушек и фонов для каталога.

Зачем это вообще нужно: настоящие афиши фильмов защищены авторским правом,
подставлять их нельзя. Но пустые карточки выглядят сломанными. Поэтому
рисуем СВОЮ графику — тёмный кинематографичный градиент с названием.
Редактор потом заменит её настоящим постером через админку.

Цвет выводится из адреса записи (slug), поэтому у каждого фильма он свой,
но стабильный: повторный запуск даёт ту же картинку.
"""

import colorsys
import hashlib
import io

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from PIL import Image, ImageDraw, ImageFont

from apps.catalog.models import Title

# Пропорции: постер вертикальный 2:3, фон широкий 16:9 — как на реальных афишах.
POSTER_SIZE = (600, 900)
BACKDROP_SIZE = (1600, 900)

# Тёмная база проекта (#0b0d12) — та же, что фон сайта.
BASE_DARK = (11, 13, 18)

# Кандидаты шрифтов по платформам: в Docker стоит DejaVu, на Windows — Arial,
# на macOS — свой Arial. Все три содержат кириллицу. Берём первый найденный,
# поэтому команда рисует нормальные постеры и без Docker (у заказчика Windows).
# Обычное начертание больше не нужно: подписи с постера убраны, осталась
# только крупная буква водяным знаком.
FONT_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


class Command(BaseCommand):
    help = "Рисует оригинальные постеры-заглушки и фоны для фильмов без картинок."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Перерисовать даже тем, у кого картинки уже есть",
        )

    def handle(self, *args, **options):
        force = options["force"]
        drawn = 0

        for title in Title.objects.all():
            accent = self._accent_color(title.slug)

            # Флаг, а не повторная проверка title.poster: после _save поле уже
            # выставлено в памяти, и условие «нет постера» стало бы ложным —
            # тогда title.save() не вызвался бы, а файл на диске осиротел.
            changed = False

            if force or not title.poster or self._file_missing(title.poster):
                self._save(title.poster, self._poster(title, accent), f"{title.slug}.jpg")
                drawn += 1
                changed = True
            if force or not title.backdrop or self._file_missing(title.backdrop):
                self._save(title.backdrop, self._backdrop(title, accent), f"{title.slug}-bg.jpg")
                changed = True

            if changed:
                # update_fields, чтобы не задеть save()-логику (published_at и т.п.).
                title.save(update_fields=["poster", "backdrop"])

        self.stdout.write(self.style.SUCCESS(f"Готово. Постеров нарисовано: {drawn}."))

    def _file_missing(self, field):
        """Файл задан в БД, но физически отсутствует на диске.

        Нужно для платформ с эфемерной файловой системой (бесплатный Render):
        после перезапуска контейнера файлы пропадают, а поле в базе остаётся
        заполненным. Без этой проверки команда считала постер «есть» и не
        перерисовывала его — витрина оставалась без картинок до --force.

        Локальному диску не доверяем (он эфемерный), поэтому смотрим именно
        в хранилище. Для S3/R2 хранилище отвечает на exists() запросом к
        бакету, и битый путь вернёт False — тоже перерисуем.
        """
        if not field or not field.name:
            return True
        try:
            return not field.storage.exists(field.name)
        except (NotImplementedError, OSError):
            # Не можем спросить хранилище — считаем файл на месте,
            # чтобы не перетирать чужие данные из-за временного сбоя.
            return False

    def _accent_color(self, slug):
        """Стабильный насыщенный цвет из адреса записи."""
        digest = hashlib.md5(slug.encode()).hexdigest()
        hue = int(digest[:2], 16) / 255
        red, green, blue = colorsys.hls_to_rgb(hue, 0.55, 0.65)
        return (int(red * 255), int(green * 255), int(blue * 255))

    def _poster(self, title, accent):
        image = self._gradient(POSTER_SIZE, accent, orientation="vertical").convert("RGBA")
        width, height = POSTER_SIZE

        # Крупная первая буква — полупрозрачный водяной знак, а не герой постера.
        # Рисуем на отдельном RGBA-слое и накладываем: на RGB альфа игнорируется.
        mark_font = self._font(FONT_BOLD, 480)
        letter = title.name[:1].upper()
        overlay = Image.new("RGBA", POSTER_SIZE, (0, 0, 0, 0))
        self._centered(ImageDraw.Draw(overlay), letter, mark_font, (width // 2, height // 2 - 40), (255, 255, 255, 22))
        image = Image.alpha_composite(image, overlay).convert("RGB")

        # Название и мета в саму картинку больше не впечатываются.

        # Настоящий постер не содержит подписей — их печатает карточка. Пока
        # заглушка их рисовала, в сетке каталога название читалось дважды:
        # внутри картинки и строкой под ней, — и это выглядело как ошибка
        # вёрстки, хотя вёрстка была ни при чём. Заглушка должна вести себя
        # как постер, иначе по ней нельзя судить о виде каталога.

        return image

    def _backdrop(self, title, accent):
        image = self._gradient(BACKDROP_SIZE, accent, orientation="horizontal").convert("RGBA")
        # На фоне только приглушённое название — он уходит под текст страницы.
        font = self._font(FONT_BOLD, 130)
        overlay = Image.new("RGBA", BACKDROP_SIZE, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).text(
            (80, BACKDROP_SIZE[1] - 230), title.name[:22], font=font, fill=(255, 255, 255, 20)
        )
        return Image.alpha_composite(image, overlay).convert("RGB")

    def _gradient(self, size, accent, orientation):
        """
        Тёмный градиент от базового цвета к приглушённому акценту.

        Рисуем линиями, а не по пикселям: строк ~600–1600 против сотен тысяч
        точек. Пиксельный цикл на 16 картинок занимал бы почти минуту.
        """
        width, height = size
        target = tuple(int(base * 0.35 + channel * 0.35) for base, channel in zip(BASE_DARK, accent))
        image = Image.new("RGB", size, BASE_DARK)
        draw = ImageDraw.Draw(image)

        if orientation == "horizontal":
            for x in range(width):
                ratio = x / width
                color = tuple(int(b + (t - b) * ratio) for b, t in zip(BASE_DARK, target))
                draw.line([(x, 0), (x, height)], fill=color)
        else:
            for y in range(height):
                ratio = y / height
                color = tuple(int(b + (t - b) * ratio) for b, t in zip(BASE_DARK, target))
                draw.line([(0, y), (width, y)], fill=color)
        return image

    def _font(self, candidates, size):
        # Перебираем кандидатов по платформам, берём первый доступный.
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
        # Ни один шрифт не найден — не падаем, берём встроенный.
        # Кириллица будет хуже, но команда отработает.
        return ImageFont.load_default(size)

    def _centered(self, draw, text, font, center, fill):
        box = draw.textbbox((0, 0), text, font=font)
        text_width, text_height = box[2] - box[0], box[3] - box[1]
        draw.text(
            (center[0] - text_width / 2 - box[0], center[1] - text_height / 2 - box[1]),
            text,
            font=font,
            fill=fill,
        )

    def _save(self, field, image, filename):
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88)
        field.save(filename, ContentFile(buffer.getvalue()), save=False)
