"""
Добавляет к уже наполненному каталогу «мясо»: съёмочную группу, ручные связи
«похожее», тематические подборки и демонстрационные отзывы.

Вынесено отдельно от seed_catalog намеренно. seed_catalog создаёт сами фильмы
и обязан оставаться простым — его тесты сторожат первое впечатление новичка.
А эта команда наполняет каталог тем, что превращает список названий в живой
кинотеатр: актёрами, режиссёрами, подборками и оценками.

Идемпотентна: повторный запуск обновляет записи, а не плодит дубликаты.
Требует, чтобы фильмы уже существовали, — сначала seed_catalog.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.models import Collection, CollectionItem, Participation, Person, Title
from apps.catalog.seed_data import COLLECTIONS, CREDITS, DEMO_USERS, PERSONS, RELATED, REVIEWS
from apps.reviews.services import save_review


class Command(BaseCommand):
    help = "Добавляет съёмочную группу, подборки и демо-отзывы. Требует seed_catalog. Идемпотентна."

    @transaction.atomic
    def handle(self, *args, **options):
        self._check_data()

        persons = self._load_persons()
        self._load_credits(persons)
        self._load_related()
        self._load_collections()
        self._load_reviews()

        self.stdout.write(self.style.SUCCESS("Контент добавлен."))

    def _check_data(self):
        """
        Проверяет ссылки до записи: опечатка в адресе персоны или фильма
        иначе всплыла бы посреди работы невнятным KeyError.
        """
        title_slugs = set(Title.objects.values_list("slug", flat=True))
        if not title_slugs:
            raise CommandError("Каталог пуст. Сначала запустите seed_catalog.")

        person_slugs = {slug for _, slug in PERSONS}

        for title_slug, credits in CREDITS.items():
            if title_slug not in title_slugs:
                raise CommandError(f"CREDITS: в каталоге нет фильма «{title_slug}»")
            for person_slug, *_ in credits:
                if person_slug not in person_slugs:
                    raise CommandError(f"CREDITS «{title_slug}»: нет персоны «{person_slug}»")

        for title_slug, related in RELATED.items():
            for slug in (title_slug, *related):
                if slug not in title_slugs:
                    raise CommandError(f"RELATED: в каталоге нет фильма «{slug}»")

        for row in COLLECTIONS:
            for title_slug in row["titles"]:
                if title_slug not in title_slugs:
                    raise CommandError(f"COLLECTIONS «{row['slug']}»: нет фильма «{title_slug}»")

        for title_slug, reviews in REVIEWS.items():
            if title_slug not in title_slugs:
                raise CommandError(f"REVIEWS: в каталоге нет фильма «{title_slug}»")
            if len(reviews) > len(DEMO_USERS):
                raise CommandError(
                    f"REVIEWS «{title_slug}»: отзывов больше, чем демо-зрителей "
                    f"({len(reviews)} > {len(DEMO_USERS)})"
                )

    def _load_persons(self):
        """Создаёт персон и возвращает их в виде {адрес: объект}."""
        persons = {}
        created = 0
        for name, slug in PERSONS:
            person, was_created = Person.objects.get_or_create(slug=slug, defaults={"name": name})
            persons[slug] = person
            created += int(was_created)

        self.stdout.write(f"Персоны: создано {created}, всего {len(PERSONS)}")
        return persons

    def _load_credits(self, persons):
        titles = {t.slug: t for t in Title.objects.filter(slug__in=CREDITS.keys())}
        count = 0
        for title_slug, credits in CREDITS.items():
            title = titles[title_slug]
            for person_slug, role, character, order in credits:
                # Ключ уникальности участия — (фильм, персона, роль): тот же
                # человек может быть в фильме и режиссёром, и актёром.
                Participation.objects.update_or_create(
                    title=title,
                    person=persons[person_slug],
                    role=role,
                    defaults={"character": character, "order": order},
                )
                count += 1

        self.stdout.write(f"Участия в проектах: {count}")

    def _load_related(self):
        titles = {t.slug: t for t in Title.objects.all()}
        for title_slug, related in RELATED.items():
            titles[title_slug].related_titles.set(titles[slug] for slug in related)

        self.stdout.write(f"Ручные «похожие»: {len(RELATED)} фильмов")

    def _load_collections(self):
        titles = {t.slug: t for t in Title.objects.all()}
        created = 0
        for position, row in enumerate(COLLECTIONS, start=1):
            collection, was_created = Collection.objects.update_or_create(
                slug=row["slug"],
                defaults={
                    "name": row["name"],
                    "description": row["description"],
                    "is_featured": row["is_featured"],
                    "is_published": True,
                    # Шаг 10 оставляет место вставить подборку между двумя
                    # существующими, не переписывая порядок у всех.
                    "order": position * 10,
                },
            )
            created += int(was_created)

            for order, title_slug in enumerate(row["titles"], start=1):
                CollectionItem.objects.update_or_create(
                    collection=collection,
                    title=titles[title_slug],
                    defaults={"order": order},
                )

        self.stdout.write(f"Подборки: всего {len(COLLECTIONS)}, новых {created}")

    def _load_reviews(self):
        """
        Создаёт демо-зрителей и их отзывы. Рейтинг у фильмов появляется как
        следствие: его пересчитывают сигналы при сохранении каждого отзыва.
        """
        user_model = get_user_model()
        users = []
        for username, email in DEMO_USERS:
            user, _ = user_model.objects.get_or_create(email=email, defaults={"username": username})
            users.append(user)

        titles = {t.slug: t for t in Title.objects.filter(slug__in=REVIEWS.keys())}
        count = 0
        for title_slug, reviews in REVIEWS.items():
            title = titles[title_slug]
            # i-й отзыв оставляет i-й зритель: один человек — один отзыв на фильм,
            # это гарантирует и уникальное ограничение в базе.
            for i, (rating, text) in enumerate(reviews):
                save_review(user=users[i], title=title, rating=rating, text=text)
                count += 1

        self.stdout.write(f"Отзывы: {count} от {len(users)} демо-зрителей")
