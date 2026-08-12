"""
Дозаполнение WebP-копий для уже загруженных картинок.

Сигнал делает копию при сохранении записи, но это помогает только новым
загрузкам. Всё, что попало в каталог до починки конвертации, копий не имеет —
а это как раз весь продакшен, где хранилище нелокальное: там конвертация
пропускалась целиком. Команда проходит по существующим записям и дозаполняет
недостающее.

Идемпотентна: файл с готовой копией пропускается без чтения оригинала.

Примеры:
    python manage.py make_webp
    python manage.py make_webp --dry-run
    python manage.py make_webp --model catalog.Title
"""

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from apps.catalog.webp import (
    IMAGE_FIELDS_BY_MODEL,
    SIZED_VARIANTS,
    convert_field,
    webp_name,
)


class Command(BaseCommand):
    help = "Создаёт WebP-копии для уже загруженных изображений."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Только посчитать, сколько копий не хватает",
        )
        parser.add_argument(
            "--model",
            help="Обработать одну модель, например catalog.Title",
        )

    def handle(self, *args, **options):
        targets = IMAGE_FIELDS_BY_MODEL
        if options["model"]:
            key = options["model"]
            if key not in targets:
                raise CommandError(
                    f"Неизвестная модель {key}. Доступны: {', '.join(sorted(targets))}"
                )
            targets = {key: targets[key]}

        created = missing = skipped = 0

        for model_key, fields in targets.items():
            model = apps.get_model(model_key)
            # only() по полям с картинками: выгружать целые записи ради
            # одного поля незачем, а записей может быть много.
            for instance in model.objects.only("pk", *fields).iterator():
                for field_name in fields:
                    field = getattr(instance, field_name, None)
                    if not field or not field.name:
                        continue

                    widths = SIZED_VARIANTS.get((model_key, field_name), ())
                    # Считаем и основную копию, и уменьшенные: без них
                    # srcset пуст, и телефон получает картинку в полный размер.
                    wanted = [webp_name(field.name)] + [
                        webp_name(field.name, width) for width in widths
                    ]

                    try:
                        absent = [n for n in wanted if not field.storage.exists(n)]
                    except Exception:
                        self.stderr.write(f"Не удалось проверить {field.name}")
                        continue

                    if not absent:
                        skipped += 1
                        continue

                    missing += 1
                    if options["dry_run"]:
                        continue
                    if convert_field(field, widths):
                        created += 1

        if options["dry_run"]:
            self.stdout.write(f"Копий не хватает: {missing}. Уже готово: {skipped}.")
            self.stdout.write("Ничего не записано: это пробный запуск.")
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово. Создано: {created} из {missing} недостающих. Пропущено готовых: {skipped}."
            )
        )
        if created < missing:
            self.stdout.write(
                "Часть копий не получилась — подробности в логах apps.catalog.webp."
            )
