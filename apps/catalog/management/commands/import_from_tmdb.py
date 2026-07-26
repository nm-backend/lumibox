"""
Импорт реальных данных о фильмах из TMDB (The Movie Database).

Использование:
    python manage.py import_from_tmdb --api-key YOUR_KEY --count 50

TMDB API бесплатен: https://www.themoviedb.org/settings/api
Ключ берётся из TMDB_API_KEY в .env или передаётся --api-key.

Импортирует:
- Фильмы и сериалы с постерами, бэкрдропами, описаниями
- Жанры
- Актёров, режиссёров
- Рейтинги
"""

import time

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import Country, Genre, Participation, Person, Title

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p"

# Маппинг TMDB country codes -> наши страны
COUNTRY_MAP = {
    "US": ("США", "ssha"),
    "GB": ("Великобритания", "velikobritaniya"),
    "FR": ("Франция", "franciya"),
    "DE": ("Германия", "germaniya"),
    "IT": ("Италия", "italiya"),
    "ES": ("Испания", "ispaniya"),
    "JP": ("Япония", "yaponiya"),
    "KR": ("Южная Корея", "yuzhnaya-koreya"),
    "IN": ("Индия", "indiya"),
    "CA": ("Канада", "kanada"),
    "RU": ("Россия", "rossiya"),
    "CN": ("Китай", "kitay"),
    "BR": ("Бразилия", "braziliya"),
    "AU": ("Австралия", "avstraliya"),
}


class Command(BaseCommand):
    help = "Импорт фильмов и сериалов из TMDB API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--api-key",
            help="TMDB API ключ (или задайте TMDB_API_KEY в .env)",
        )
        parser.add_argument(
            "--count",
            type=int,
            default=20,
            help="Количество фильмов для импорта (по умолчанию 20)",
        )
        parser.add_argument(
            "--type",
            choices=["movie", "tv", "both"],
            default="both",
            help="Тип контента: movie, tv или both",
        )
        parser.add_argument(
            "--language",
            default="ru-RU",
            help="Язык описаний (по умолчанию ru-RU)",
        )

    def handle(self, *args, **options):
        api_key = options["api_key"] or getattr(settings, "TMDB_API_KEY", "")
        if not api_key:
            raise CommandError(
                "TMDB API ключ не задан. Используйте --api-key или TMDB_API_KEY в .env\n"
                "Получить: https://www.themoviedb.org/settings/api"
            )

        self.api_key = api_key
        self.language = options["language"]
        self.session = requests.Session()
        self.session.params = {"api_key": api_key, "language": self.language}

        # Импортируем жанры
        self._import_genres()

        count = options["count"]
        content_type = options["type"]

        imported = 0
        if content_type in ("movie", "both"):
            imported += self._import_trending("movie", count if content_type == "movie" else count // 2)
        if content_type in ("tv", "both"):
            imported += self._import_trending("tv", count if content_type == "tv" else count // 2)

        self.stdout.write(self.style.SUCCESS(f"\n✓ Импортировано: {imported} записей"))

    def _api_get(self, path, **params):
        """Запрос к TMDB API с обработкой ошибок."""
        url = f"{TMDB_BASE}{path}"
        resp = self.session.get(url, params=params, timeout=15)
        if resp.status_code == 429:
            self.stdout.write("⏳ Rate limit, ждём 10 сек...")
            time.sleep(10)
            return self._api_get(path, **params)
        resp.raise_for_status()
        return resp.json()

    def _import_genres(self):
        """Импорт жанров из TMDB."""
        for content_type in ("movie", "tv"):
            data = self._api_get(f"/genre/{content_type}/list")
            for g in data.get("genres", []):
                slug = self._transliterate(g["name"])
                Genre.objects.get_or_create(
                    slug=slug,
                    defaults={"name": g["name"]},
                )
        self.stdout.write("✓ Жанры синхронизированы")

    def _import_trending(self, content_type, count):
        """Импорт trending фильмов/сериалов."""
        imported = 0
        pages = (count // 20) + 1

        for page in range(1, pages + 1):
            if imported >= count:
                break

            data = self._api_get(
                "/trending/{media_type}/week".format(
                    media_type="movie" if content_type == "movie" else "tv"
                ),
                page=page,
            )

            for item in data.get("results", []):
                if imported >= count:
                    break

                try:
                    if content_type == "movie":
                        self._import_movie(item)
                    else:
                        self._import_tv(item)
                    imported += 1
                    self.stdout.write(f"  [{imported}/{count}] {item.get('title') or item.get('name')}")
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  ⚠ Ошибка: {e}"))

                time.sleep(0.25)  # Rate limiting

        return imported

    def _import_movie(self, item):
        """Импорт одного фильма."""
        tmdb_id = item["id"]
        slug = f"tmdb-movie-{tmdb_id}"

        if Title.objects.filter(slug=slug).exists():
            self.stdout.write(f"  → Уже есть: {item['title']}")
            return

        # Получаем детали
        details = self._api_get(f"/movie/{tmdb_id}", append_to_response="credits")

        title = Title.objects.create(
            type=Title.Type.MOVIE,
            name=details.get("title", item.get("title", "")),
            original_name=details.get("original_title", ""),
            slug=slug,
            description=details.get("overview", ""),
            short_description=details.get("tagline", ""),
            release_year=int(details.get("release_date", "0000")[:4]) or 2020,
            duration_minutes=details.get("runtime"),
            status=Title.Status.PUBLISHED,
            rating_average=round(details.get("vote_average", 0), 1) if details.get("vote_average") else None,
            rating_count=details.get("vote_count", 0),
        )

        # Жанры
        genre_ids = [g["id"] for g in details.get("genres", [])]
        self._set_genres(title, genre_ids)

        # Страны
        for country in details.get("production_countries", []):
            self._set_country(title, country.get("iso_3166_1", ""))

        # Постер и бэкрдроп
        self._download_image(title, details, "poster_path", "poster", "posters")
        self._download_image(title, details, "backdrop_path", "backdrop", "backdrops")

        # Съёмочная группа
        self._import_credits(title, details.get("credits", {}))

    def _import_tv(self, item):
        """Импорт одного сериала."""
        tmdb_id = item["id"]
        slug = f"tmdb-tv-{tmdb_id}"

        if Title.objects.filter(slug=slug).exists():
            self.stdout.write(f"  → Уже есть: {item['name']}")
            return

        details = self._api_get(f"/tv/{tmdb_id}", append_to_response="credits")

        title = Title.objects.create(
            type=Title.Type.SERIES,
            name=details.get("name", item.get("name", "")),
            original_name=details.get("original_name", ""),
            slug=slug,
            description=details.get("overview", ""),
            short_description=details.get("tagline", ""),
            release_year=int(details.get("first_air_date", "0000")[:4]) or 2020,
            duration_minutes=details.get("episode_run_time", [None])[0] if details.get("episode_run_time") else None,
            status=Title.Status.PUBLISHED,
            rating_average=round(details.get("vote_average", 0), 1) if details.get("vote_average") else None,
            rating_count=details.get("vote_count", 0),
        )

        # Жанры
        genre_ids = [g["id"] for g in details.get("genres", [])]
        self._set_genres(title, genre_ids)

        # Страны
        for country_code in details.get("origin_country", []):
            self._set_country(title, country_code)

        # Постер и бэкрдроп
        self._download_image(title, details, "poster_path", "poster", "posters")
        self._download_image(title, details, "backdrop_path", "backdrop", "backdrops")

        # Съёмочная группа
        self._import_credits(title, details.get("credits", {}))

    def _set_genres(self, title, genre_ids):
        """Привязка жанров по TMDB ID."""
        from apps.catalog.models import Genre

        genre_data = self._api_get("/genre/movie/list")
        id_to_name = {g["id"]: g["name"] for g in genre_data.get("genres", [])}

        genres = []
        for gid in genre_ids:
            name = id_to_name.get(gid)
            if name:
                slug = self._transliterate(name)
                genre, _ = Genre.objects.get_or_create(slug=slug, defaults={"name": name})
                genres.append(genre)
        title.genres.set(genres)

    def _set_country(self, title, iso_code):
        """Привязка страны по ISO коду."""
        if iso_code in COUNTRY_MAP:
            name, slug = COUNTRY_MAP[iso_code]
            country, _ = Country.objects.get_or_create(slug=slug, defaults={"name": name})
            title.countries.add(country)

    def _download_image(self, title, details, tmdb_field, model_field, subdir):
        """Скачивание постера или бэкрдропа из TMDB."""
        path = details.get(tmdb_field)
        if not path:
            return

        size = "w500" if model_field == "poster" else "w1280"
        url = f"{TMDB_IMG}/{size}{path}"

        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            filename = path.lstrip("/")
            getattr(title, model_field).save(filename, ContentFile(resp.content), save=True)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  ⚠ Не удалось скачать {model_field}: {e}"))

    def _import_credits(self, title, credits):
        """Импорт актёров и режиссёров."""
        # Режиссёры
        for crew in credits.get("crew", [])[:5]:
            if crew.get("job") != "Director":
                continue
            person = self._get_or_create_person(crew)
            Participation.objects.get_or_create(
                title=title,
                person=person,
                role=Participation.Role.DIRECTOR,
            )

        # Актёры (топ-10)
        for cast in credits.get("cast", [])[:10]:
            person = self._get_or_create_person(cast)
            Participation.objects.get_or_create(
                title=title,
                person=person,
                role=Participation.Role.ACTOR,
                defaults={"character": cast.get("character", "")},
            )

    def _get_or_create_person(self, data):
        """Получить или создать персону."""
        tmdb_id = data["id"]
        slug = f"tmdb-person-{tmdb_id}"

        person, created = Person.objects.get_or_create(
            slug=slug,
            defaults={"name": data.get("name", "Unknown")},
        )

        if created and data.get("profile_path"):
            url = f"{TMDB_IMG}/w185{data['profile_path']}"
            try:
                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()
                person.photo.save(data["profile_path"].lstrip("/"), ContentFile(resp.content), save=True)
            except Exception:
                pass

        return person

    def _transliterate(self, text):
        """Транслитерация для slug."""
        import re

        # Сначала пробуем взять slug из имени
        slug = text.lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[-\s]+", "-", slug)
        return slug[:80] or "item"
