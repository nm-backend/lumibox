"""
Автоматическое сопоставление видео внешнего сервиса с записями каталога.

Раньше редактор вручную заполнял kp_id/imdb_id у каждой записи — это
дорого на каталоге в тысячи позиций. Здесь живёт команда, которая тянет
список видео из API видеосервиса и проставляет ID сама, по совпадению
названия (русского, английского или оригинального) и года выпуска.

Вместе с kp_id/imdb_id заполняется player_id — ID видео для плеера
(data-id из embed_code записи, официальный формат тега:
<ins data-type="movie" data-id="…">). Внутренний id из списка API
с ним не совпадает (проверено: расхождение у всех записей), поэтому
берём именно data-id; kp/imdb-типы резолвятся сервером плеера отдельно.

Правила, чтобы не наставить чужих ID:

- Заполняем только пустые поля: вручную введённый kp_id не затирается,
  даже если API предлагает другой.
- Год — стоп-фактор: если у записи сайта и у видео сервиса годы
  различаются, это разные фильмы с одинаковым названием, такое
  совпадение пропускаем.
- Тип (фильм/сериал) не фильтруем: в каталоге сервиса мультфильмы и
  шоу лежат среди movie/serial, и жёсткий фильтр оставил бы их без плеера.

То же правило «только пустые поля» действует для обогащения записи:
описание, рейтинги, длительность и оригинальное название приходят из
краткой карточки API (GET /videos/links), жанры и страны заводятся
в справочники, если их ещё нет.

Серии сериалов (сезоны и эпизоды) импортируются отдельной функцией
sync_series_episodes через detail-эндпоинты GET /serials/kp|imdb/{id}.
"""

import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from apps.catalog.models import Country, Episode, Genre, Title
from apps.catalog.models.video_service import VideoServiceSyncState
from apps.catalog.video_service_api import (
    VideoServiceAPIError,
    VideoServiceNotFoundError,
    fetch_serial_by_imdb,
    fetch_serial_by_kp,
    iter_video_links,
)

# Всё, кроме букв, цифр и пробелов, — разделители. re.UNICODE (по умолчанию
# в Python 3) оставляет кириллицу нетронутой, так что «Ёлка» и «елка»
# сравниваются честно, без потери регистра знаков.
_NON_WORD = re.compile(r"[^\w\s]+", re.UNICODE)
_WS = re.compile(r"\s+")

# Плеер ждёт data-type="movie" или "series", а API отдаёт "movie"/"serial":
# маппим тип списка на тип тега, чтобы не отдавать SDK невалидное значение.
_API_TO_TAG_TYPE = {"movie": "movie", "serial": "series"}


def _embed_player(item):
    """
    (player_id, player_type) записи API из её embed_code.

    Поле id в списке — внутренний ID записи в базе сервиса, и он не
    совпадает с ID контента плеера (data-id из embed_code): проверено
    на всех 160 записях первых страниц — расхождение у каждой. Плеер
    ждёт именно data-id, поэтому при наличии embed_code берём ID из
    него, иначе (вдруг сервис уберёт поле) — внутренний id записи.
    Тип маппим так же, как у обычного item.
    """
    match = re.search(r'data-id="(\d+)"', item.get("embed_code") or "")
    if match:
        return match.group(1), _API_TO_TAG_TYPE.get(item.get("type"))
    return str(item.get("id") or ""), _API_TO_TAG_TYPE.get(item.get("type"))


def normalize_name(name):
    """Приводит название к единому виду для сравнения: «ЁЛКА!» → «ёлка»."""
    if not name:
        return ""
    return _WS.sub(" ", _NON_WORD.sub(" ", str(name))).strip().lower()


def build_title_index():
    """
    Индекс названий записей, которым ещё нужен внешний ID.

    В индексе только те тайтлы, где пуст хотя бы один из идентификаторов:
    полностью заполненные записи пропускаем ещё до загрузки списка. Каждое
    название (русское и оригинальное) ведёт на список кандидатов — одно имя
    могут носить разные фильмы, решает год.
    """
    index = {}
    titles = Title.objects.filter(
        Q(kp_id="") | Q(imdb_id="") | Q(player_id="")
    ).only(
        "pk", "name", "original_name", "release_year", "kp_id", "imdb_id",
        "player_id", "player_type", "description", "short_description",
        "duration_minutes", "kp_rating", "imdb_rating",
    )
    for title in titles:
        for candidate in (title.name, title.original_name):
            norm = normalize_name(candidate)
            if not norm:
                continue
            candidates = index.setdefault(norm, [])
            # Тайтл может один раз попасть в список: оба поля (name и
            # original_name) иногда нормализуются в одно и то же значение.
            if not candidates or candidates[-1].pk != title.pk:
                candidates.append(title)
    return index


def _filter_years(index):
    """
    Годы для фильтра year[], если им можно доверять, иначе None.

    Фильтр отсекает видео несовпадающих лет ещё на стороне API — первый
    полный прогон тогда обходит не весь каталог (десятки тысяч видео),
    а только его часть. Но год — стоп-фактор сопоставления: если хоть
    у одной записи каталога год не известен, фильтровать нельзя — под
    него видео нашлось бы и с любым другим годом. Возвращаем None,
    и синк обходит весь список, как раньше.
    """
    if not index:
        return None
    years = set()
    for candidates in index.values():
        for title in candidates:
            if not title.release_year:
                return None
            years.add(title.release_year)
    return sorted(years)


def match_item(index, item):
    """Возвращает тайтл для записи API или None, если совпадений нет."""
    year_value = item.get("year")
    year = int(year_value) if str(year_value).isdigit() else None

    for field in ("name", "name_rus", "name_eng", "name_original"):
        norm = normalize_name(item.get(field))
        if not norm:
            continue
        for title in index.get(norm, []):
            if year and title.release_year and title.release_year != year:
                continue
            return title
    return None


def sync_video_service_ids(*, full=False, dry_run=False, page_size=100, max_pages=None):
    """
    Прогоняет синхронизацию и возвращает статистику.

    full=False — инкрементальный запуск: в API уходит сохранённый
    updated_from, а после успешного завершения он обновляется на «сейчас».
    dry_run=True ничего не пишет в базу (ни ID, ни состояние).

    Возвращает словарь счётчиков: fetched, matched, kp_filled, imdb_filled,
    player_filled, enriched (записей, чьи поля обогащены), genres_added,
    countries_added.
    """
    api_key = (settings.VIDEO_SERVICE_API_KEY or "").strip()
    if not api_key:
        from apps.catalog.video_service_api import VideoServiceAPIError

        raise VideoServiceAPIError(
            "VIDEO_SERVICE_API_KEY не задан — синхронизацию невозможно запустить"
        )

    state = VideoServiceSyncState.get_solo()
    updated_from = None if full else state.last_updated_from

    index = build_title_index()
    # Быстрый путь: все записи каталога знают свой год — передаём их в API
    # фильтром year[] и не обходим весь список (см. _filter_years).
    years = _filter_years(index)
    stats = {
        "fetched": 0, "matched": 0, "kp_filled": 0, "imdb_filled": 0,
        "player_filled": 0, "enriched": 0, "genres_added": 0,
        "countries_added": 0,
    }

    for item in iter_video_links(
        api_key,
        limit=page_size,
        updated_from=updated_from,
        years=years,
        max_pages=max_pages,
    ):
        stats["fetched"] += 1
        title = match_item(index, item)
        if title is None:
            continue
        stats["matched"] += 1

        changes = {}
        if not title.kp_id and item.get("kp_id"):
            changes["kp_id"] = str(item["kp_id"])
        if not title.imdb_id and item.get("imdb_id"):
            changes["imdb_id"] = str(item["imdb_id"])

        # player_id — ID видео для плеера: data-id из embed_code записи
        # (внутренний id из списка с ним не совпадает — см. _embed_player).
        # Тип маппим на значения SDK (movie/series); заполняем только
        # пустые поля.
        player_id, embed_type = _embed_player(item)
        if not title.player_id and player_id:
            changes["player_id"] = player_id
        if not title.player_type and embed_type:
            changes["player_type"] = embed_type

        # Обогащение записи: описание, рейтинги, жанры, страны — тоже
        # только пустые поля, чтобы не затирать ручную работу редактора.
        enrich_fields, genre_names, country_names = _collect_enrichment(title, item)
        changes.update(enrich_fields)

        # Жанры и страны добавляем лишь когда у записи их ещё нет вовсе:
        # набор, собранный редактором вручную, не трогаем.
        needs_genres = bool(genre_names) and not title.genres.exists()
        needs_countries = bool(country_names) and not title.countries.exists()

        if not changes and not needs_genres and not needs_countries:
            continue

        if enrich_fields or genre_names or country_names:
            stats["enriched"] += 1

        if not dry_run:
            if changes:
                Title.objects.filter(pk=title.pk).update(**changes)
            if needs_genres:
                for name in genre_names:
                    genre = _ensure_reference(Genre, name, "genre")
                    if genre is not None:
                        title.genres.add(genre)
                        stats["genres_added"] += 1
            if needs_countries:
                for name in country_names:
                    country = _ensure_reference(Country, name, "country")
                    if country is not None:
                        title.countries.add(country)
                        stats["countries_added"] += 1
        if "kp_id" in changes:
            stats["kp_filled"] += 1
        if "imdb_id" in changes:
            stats["imdb_filled"] += 1
        if "player_id" in changes:
            stats["player_filled"] += 1

    if not dry_run:
        state.last_updated_from = timezone.now()
        state.save(update_fields=["last_updated_from", "updated_at"])

    return stats


def _names(values):
    """Названия из поля-списка API: строки или словари {id, name} → [name]."""
    names = []
    for value in values or []:
        if isinstance(value, dict):
            value = value.get("name")
        name = (value or "").strip()
        if name:
            names.append(name)
    return names


def _parse_rating(value):
    """
    Рейтинг из API в Decimal (0–10) или None, если значение некорректно.

    API отдаёт рейтинг строкой («8.1») или null. Мусор вроде «N/A»
    молча пропускаем: ставить в запись случайное число хуже, чем оставить
    поле пустым. Округляем до десятых, чтобы уложиться в формат поля.
    """
    if value in (None, ""):
        return None
    try:
        rating = Decimal(str(value)).quantize(Decimal("0.1"))
    except (InvalidOperation, ValueError):
        return None
    if not Decimal("0") <= rating <= Decimal("10"):
        return None
    return rating


def _collect_enrichment(title, item):
    """
    Пустые поля записи, которые можно заполнить из карточки API.

    То же правило, что у ID: заполняем только пустое. Возвращает кортеж
    (field_changes, genre_names, country_names): первые уходят в .update(),
    жанры и страны — связи многие-ко-многим, их добавляем отдельно.
    """
    fields = {}

    if not title.description:
        description = (item.get("description") or item.get("description_short") or "")
        description = description.strip()
        if description:
            fields["description"] = description
    if not title.short_description:
        short = (item.get("description_short") or "").strip()
        if short:
            fields["short_description"] = short
    if not title.original_name:
        original = (item.get("name_original") or item.get("name_eng") or "").strip()
        if original:
            fields["original_name"] = original

    if title.duration_minutes is None:
        try:
            minutes = int(item.get("duration"))
        except (TypeError, ValueError):
            minutes = 0
        if minutes > 0:
            fields["duration_minutes"] = minutes

    for field in ("kp_rating", "imdb_rating"):
        if getattr(title, field) is not None:
            continue
        rating = _parse_rating(item.get(field))
        if rating is not None:
            fields[field] = rating

    return fields, _names(item.get("genre")), _names(item.get("country"))


def _unique_slug(model, name, fallback):
    """
    Свободный адрес для новой справочной записи.

    slugify кириллицы даёт пустую строку, а два разных названия могут дать
    один адрес — в обоих случаях запись не создалась бы. Добавляем числовой
    хвост, пока адрес не окажется свободным.
    """
    base = slugify(name, allow_unicode=False) or fallback
    slug, suffix = base, 2
    while model.objects.filter(slug=slug).exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _ensure_reference(model, name, fallback):
    """Находит справочную запись по названию или создаёт новую."""
    obj = model.objects.filter(name__iexact=name).first()
    if obj is not None:
        return obj
    return model.objects.create(name=name, slug=_unique_slug(model, name, fallback))


def _parse_season_number(value, index):
    """Номер сезона: число из названия сезона API или порядковый номер."""
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    return index


def _import_episodes(title, payload, *, dry_run):
    """
    Создаёт недостающие серии сериала из ответа API; возвращает число новых.

    Пары «сезон + серия» уникальны в пределах записи (constraint
    episode_title_season_episode_uniq), существующие пропускаем — повторный
    запуск ничего не дублирует. Номера серий внутри сезона API не отдаёт,
    берём их по порядку следования.
    """
    seasons = payload.get("seasons") or []
    created = 0
    for index, season in enumerate(seasons, start=1):
        season_number = _parse_season_number(season.get("name"), index)
        for episode_number, series in enumerate(season.get("series") or [], start=1):
            exists = Episode.objects.filter(
                title=title,
                season_number=season_number,
                episode_number=episode_number,
            ).exists()
            if exists:
                continue
            created += 1
            if not dry_run:
                Episode.objects.create(
                    title=title,
                    season_number=season_number,
                    episode_number=episode_number,
                    name=str(series.get("name") or "").strip(),
                )
    return created


def sync_series_episodes(*, dry_run=False, limit=None):
    """
    Импортирует серии сериалов из API (GET /serials/kp|imdb/{id}).

    Обрабатывает записи каталога с kp_id/imdb_id, у которых нет ни одной
    серии. Эндпоинт живёт без префикса /publisher — см. комментарий
    в video_service_api.py; с верным адресом он отдаёт сезоны и серии.

    dry_run=True ничего не пишет в базу. Возвращает словарь счётчиков:
    processed (записей каталога), created (созданных серий), not_found
    (нет в каталоге сервиса), errors (ошибок API).
    """
    api_key = (settings.VIDEO_SERVICE_API_KEY or "").strip()
    if not api_key:
        raise VideoServiceAPIError(
            "VIDEO_SERVICE_API_KEY не задан — синхронизацию невозможно запустить"
        )

    titles = (
        Title.objects.filter(Q(kp_id__gt="") | Q(imdb_id__gt=""))
        .filter(episodes__isnull=True)
        .order_by("pk")
    )
    if limit is not None:
        titles = titles[:limit]

    stats = {"processed": 0, "created": 0, "not_found": 0, "errors": 0}
    for title in titles:
        stats["processed"] += 1
        try:
            if title.kp_id.strip():
                payload = fetch_serial_by_kp(api_key, title.kp_id.strip())
            else:
                payload = fetch_serial_by_imdb(api_key, title.imdb_id.strip())
        except VideoServiceNotFoundError:
            stats["not_found"] += 1
            continue
        except VideoServiceAPIError:
            stats["errors"] += 1
            continue
        stats["created"] += _import_episodes(title, payload, dry_run=dry_run)
    return stats
