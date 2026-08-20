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
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

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
    fetch_video_by_imdb,
    fetch_video_by_kp,
    get_vibix_api_token,
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

    Поле id в списке — внутренний ID ресурса API, и оно не обязано
    совпадать с ID контента плеера. Плеер ждёт именно data-id из
    embed_code; если кода нет, player_id не заполняем и используем
    безопасный KP/IMDb fallback. Тип маппим к значениям SDK.
    """
    match = re.search(r'data-id="(\d+)"', item.get("embed_code") or "")
    if match:
        return match.group(1), _API_TO_TAG_TYPE.get(item.get("type"))
    # Поле item.id — ID ресурса API, а не контракт плеера. Подставлять его
    # как data-id нельзя: при отсутствии embed_code оставляем player_id
    # пустым, и страница безопасно использует kp/imdb fallback.
    return "", _API_TO_TAG_TYPE.get(item.get("type"))


def normalize_name(name):
    """Приводит название к единому виду для сравнения: «ЁЛКА!» → «ёлка»."""
    if not name:
        return ""
    return _WS.sub(" ", _NON_WORD.sub(" ", str(name))).strip().lower()


@dataclass
class TitleMatchIndex:
    """Индексы локального каталога для однозначного сопоставления."""

    titles: list[Title]
    by_name: dict[str, list[Title]]
    by_kp: dict[str, list[Title]]
    by_imdb: dict[str, list[Title]]


def _append_candidate(index, key, title):
    if not key:
        return
    candidates = index.setdefault(key, [])
    if all(candidate.pk != title.pk for candidate in candidates):
        candidates.append(title)


def build_title_index():
    """Индексы записей, которым ещё нужны данные Vibix.

    KP/IMDb являются первичными ключами сопоставления. Название и год —
    только fallback для записей без внешних ID; неоднозначное совпадение
    намеренно пропускается вместо назначения чужого видео.
    """
    titles = list(
        Title.objects.filter(Q(kp_id="") | Q(imdb_id="") | Q(player_id=""))
        .only(
            "pk", "name", "original_name", "release_year", "kp_id", "imdb_id",
            "player_id", "player_type", "description", "short_description",
            "duration_minutes", "kp_rating", "imdb_rating",
        )
    )
    result = TitleMatchIndex(titles=titles, by_name={}, by_kp={}, by_imdb={})
    for title in titles:
        _append_candidate(result.by_kp, title.kp_id.strip(), title)
        _append_candidate(result.by_imdb, title.imdb_id.strip().lower(), title)
        for candidate in (title.name, title.original_name):
            _append_candidate(result.by_name, normalize_name(candidate), title)
    return result


def _filter_years(index):
    """Годы локальных записей для серверного фильтра ``year[]``."""
    titles = index.titles if isinstance(index, TitleMatchIndex) else []
    if not titles:
        return None
    if any(not title.release_year for title in titles):
        return None
    return sorted({title.release_year for title in titles})


def _one_candidate(candidates):
    """Единственный кандидат или None при отсутствии/неоднозначности."""
    return candidates[0] if len(candidates) == 1 else None


def match_item(index, item):
    """Однозначно сопоставляет ресурс API с локальной записью."""
    kp_id = str(item.get("kp_id") or item.get("kinopoisk_id") or "").strip()
    if kp_id:
        exact = _one_candidate(index.by_kp.get(kp_id, []))
        if exact is not None:
            return exact

    imdb_id = str(item.get("imdb_id") or "").strip().lower()
    if imdb_id:
        exact = _one_candidate(index.by_imdb.get(imdb_id, []))
        if exact is not None:
            return exact

    year_value = item.get("year")
    year = int(year_value) if str(year_value).isdigit() else None
    matched = {}
    for field in ("name", "name_rus", "name_eng", "name_original"):
        norm = normalize_name(item.get(field))
        for title in index.by_name.get(norm, []):
            if year and title.release_year and title.release_year != year:
                continue
            matched[title.pk] = title

    return _one_candidate(list(matched.values()))


def sync_title(title, *, dry_run=False):
    """
    Синхронизирует одну запись каталога с видеосервисом.

    Тип записи определяет эндпоинт: сериал — GET /serials/kp|imdb/{id}
    (сезоны и серии), всё остальное — GET /videos/kp|imdb/{id} (карточка).
    Проставляет player_id/player_type из embed_code записи сервиса и
    обогащает пустые поля записи (описание, рейтинги, жанры, страны) —
    то же правило «только пустые», что и у массового синка: ручная работа
    редактора не затирается, повторный запуск идемпотентен. Если фильм
    оказался сериалом (в карточке пришли сезоны) — серии импортируются
    тоже. Ничего не удаляет.

    Возвращает словарь счётчиков: matched, not_found, player_filled,
    enriched, episodes_created.
    """
    api_key = get_vibix_api_token()
    if not api_key:
        raise VideoServiceAPIError(
            "VIBIX_API_TOKEN не задан — синхронизацию невозможно запустить"
        )

    kp_id = title.kp_id.strip()
    imdb_id = title.imdb_id.strip()
    if not kp_id and not imdb_id:
        raise ValueError(
            f"У записи «{title.name}» нет kp_id/imdb_id — синхронизировать нечего"
        )

    stats = {"matched": 0, "not_found": 0, "player_filled": 0, "enriched": 0, "episodes_created": 0}
    try:
        if title.is_series:
            payload = (
                fetch_serial_by_kp(api_key, kp_id) if kp_id else fetch_serial_by_imdb(api_key, imdb_id)
            )
            # У /serials/{id} нет embed_code и type (только id, name, seasons):
            # player_id/player_type для тега плеера берём из карточки
            # /videos/{kp|imdb}/{id}, её же используем для обогащения. Если
            # карточки нет — плеер останется на kp/imdb-типе, а серии всё
            # равно импортируются из payload.
            try:
                embed_payload = (
                    fetch_video_by_kp(api_key, kp_id) if kp_id else fetch_video_by_imdb(api_key, imdb_id)
                )
            except VideoServiceNotFoundError:
                embed_payload = None
        else:
            payload = (
                fetch_video_by_kp(api_key, kp_id) if kp_id else fetch_video_by_imdb(api_key, imdb_id)
            )
            embed_payload = payload
    except VideoServiceNotFoundError:
        stats["not_found"] = 1
        return stats
    stats["matched"] = 1

    player_id, embed_type = (
        _embed_player(embed_payload) if embed_payload is not None else (None, None)
    )
    changes = {}
    if not title.player_id and player_id:
        changes["player_id"] = player_id
    if not title.player_type and embed_type:
        changes["player_type"] = embed_type

    # Обогащаем из карточки /videos (полное описание, рейтинги, жанры),
    # для сериала — из её же embed_payload, а не из короткого ответа
    # /serials, где этих полей нет.
    enrich_source = embed_payload if embed_payload is not None else payload
    enrich_fields, genre_names, country_names = _collect_enrichment(title, enrich_source)
    changes.update(enrich_fields)

    if changes and not dry_run:
        Title.objects.filter(pk=title.pk).update(**changes)
    if "player_id" in changes:
        stats["player_filled"] = 1
    if enrich_fields or genre_names or country_names:
        stats["enriched"] = 1

    needs_genres = bool(genre_names) and not title.genres.exists()
    needs_countries = bool(country_names) and not title.countries.exists()
    if not dry_run:
        if needs_genres:
            for name in genre_names:
                genre = _ensure_reference(Genre, name, "genre")
                if genre is not None:
                    title.genres.add(genre)
        if needs_countries:
            for name in country_names:
                country = _ensure_reference(Country, name, "country")
                if country is not None:
                    title.countries.add(country)

    seasons = payload.get("seasons")
    if seasons is not None and not title.is_series:
        # Карточка фильма пришла с сезонами — запись на деле сериал
        # (в каталоге сервиса типы не разделены строго). Импортируем серии,
        # player_type для плеера останется из embed_code.
        stats["episodes_created"] = _import_episodes(title, payload, dry_run=dry_run)
    elif title.is_series:
        stats["episodes_created"] = _import_episodes(title, payload, dry_run=dry_run)

    return stats


def _parse_year(value):
    """
    Год выпуска из ответа API в диапазон, допустимый моделью, иначе None.

    API отдаёт год строкой ("2010") и изредка мусором. Модель принимает
    1888–2100 (см. Title.release_year), выход за границы — не год, а брак
    данных: такую карточку заводить нельзя, год обязателен.
    """
    match = re.search(r"\d{4}", str(value or ""))
    if not match:
        return None
    year = int(match.group())
    return year if 1888 <= year <= 2100 else None


def create_title_from_vibix(api_key, kp_id, *, dry_run=False):
    """
    Заводит запись каталога из карточки видеосервиса по Kinopoisk ID.

    В отличие от sync_video_service_ids (обогащает уже существующие записи),
    здесь запись создаётся с нуля по ответу /videos/kp/{id}: название, год,
    kp_id/imdb_id, player_id из embed_code, а также описание, рейтинги,
    длительность, жанры и страны — тем же набором правил, что и обогащение.
    Так каталог наполняется по списку Kinopoisk ID без ручного ввода.

    Возвращает (title|None, outcome), где outcome — одно из:
    'created' | 'exists' | 'not_found' | 'no_name' | 'no_year'.

    Идемпотентно: если запись с таким kp_id уже есть, возвращает её
    с outcome='exists' и ничего не меняет — повторный прогон списка
    не плодит дубли. dry_run=True не пишет в базу и возвращает title=None.
    """
    kp_id = str(kp_id or "").strip()
    if not kp_id:
        return None, "no_name"

    existing = Title.objects.filter(kp_id=kp_id).first()
    if existing is not None:
        return existing, "exists"

    try:
        item = fetch_video_by_kp(api_key, kp_id)
    except VideoServiceNotFoundError:
        return None, "not_found"

    # Русское название приоритетнее: каталог русскоязычный. name — запасной
    # вариант (API кладёт в него ru либо en), name_eng уходит в оригинальное.
    name = (item.get("name_rus") or item.get("name") or "").strip()
    if not name:
        return None, "no_name"

    year = _parse_year(item.get("year"))
    if year is None:
        return None, "no_year"

    if dry_run:
        return None, "created"

    title = Title(
        type=Title.Type.SERIES if item.get("type") == "serial" else Title.Type.MOVIE,
        name=name,
        release_year=year,
        kp_id=kp_id,
        imdb_id=(item.get("imdb_id") or "").strip(),
        status=Title.Status.PUBLISHED,
        slug=_unique_slug(Title, name, kp_id),
    )

    # player_id из embed_code — точный ID контента плеера; при его отсутствии
    # поле пустое, и страница безопасно резолвит контент по kp_id (тот же
    # fallback, что у обогащения существующих записей).
    player_id, embed_type = _embed_player(item)
    if player_id:
        title.player_id = player_id
        if embed_type:
            title.player_type = embed_type

    enrich_fields, genre_names, country_names = _collect_enrichment(title, item)
    for field, value in enrich_fields.items():
        setattr(title, field, value)

    title.save()

    for genre_name in genre_names:
        genre = _ensure_reference(Genre, genre_name, "genre")
        if genre is not None:
            title.genres.add(genre)
    for country_name in country_names:
        country = _ensure_reference(Country, country_name, "country")
        if country is not None:
            title.countries.add(country)

    return title, "created"


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
    api_key = get_vibix_api_token()
    if not api_key:
        from apps.catalog.video_service_api import VideoServiceAPIError

        raise VideoServiceAPIError(
            "VIBIX_API_TOKEN не задан — синхронизацию невозможно запустить"
        )

    # Watermark фиксируем ДО обхода страниц. Если ресурс изменится во время
    # долгой синхронизации, следующий запуск снова его увидит; отметка
    # «время окончания» могла бы навсегда пропустить такое изменение.
    sync_started_at = timezone.now()
    state = VideoServiceSyncState.objects.filter(key="default").first()
    updated_from = None if full or state is None else state.last_updated_from

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
        VideoServiceSyncState.objects.update_or_create(
            key="default",
            defaults={"last_updated_from": sync_started_at},
        )

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
    """Номер сезона из ``1``/``Сезон 1`` или порядковый fallback."""
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else index


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

    Обрабатывает все сериалы с kp_id/imdb_id. Уже существующие пары
    «сезон + серия» пропускаются, поэтому повторный запуск не создаёт
    дубли, но способен добавить новый сезон к ранее синхронизированной
    записи. Эндпоинт живёт без префикса /publisher.

    dry_run=True ничего не пишет в базу. Возвращает словарь счётчиков:
    processed (записей каталога), created (созданных серий), not_found
    (нет в каталоге сервиса), errors (ошибок API).
    """
    api_key = get_vibix_api_token()
    if not api_key:
        raise VideoServiceAPIError(
            "VIBIX_API_TOKEN не задан — синхронизацию невозможно запустить"
        )

    titles = (
        Title.objects.series()
        .filter(Q(kp_id__gt="") | Q(imdb_id__gt=""))
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
