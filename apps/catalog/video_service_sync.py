"""
Автоматическое сопоставление видео внешнего сервиса с записями каталога.

Раньше редактор вручную заполнял kp_id/imdb_id у каждой записи — это
дорого на каталоге в тысячи позиций. Здесь живёт команда, которая тянет
список видео из API видеосервиса и проставляет ID сама, по совпадению
названия (русского, английского или оригинального) и года выпуска.

Вместе с kp_id/imdb_id заполняется player_id — внутренний ID видео
из списка API (поле id, то самое, что плеер ждёт в data-id). Вкладка
плеера отдаёт ему предпочтение: это официальный формат тега
(<ins data-type="movie" data-id="…">), тогда как kp/imdb-типы
резолвятся сервером плеера отдельно.

Правила, чтобы не наставить чужих ID:

- Заполняем только пустые поля: вручную введённый kp_id не затирается,
  даже если API предлагает другой.
- Год — стоп-фактор: если у записи сайта и у видео сервиса годы
  различаются, это разные фильмы с одинаковым названием, такое
  совпадение пропускаем.
- Тип (фильм/сериал) не фильтруем: в каталоге сервиса мультфильмы и
  шоу лежат среди movie/serial, и жёсткий фильтр оставил бы их без плеера.
"""

import re

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import Title
from apps.catalog.models.video_service import VideoServiceSyncState
from apps.catalog.video_service_api import iter_video_links

# Всё, кроме букв, цифр и пробелов, — разделители. re.UNICODE (по умолчанию
# в Python 3) оставляет кириллицу нетронутой, так что «Ёлка» и «елка»
# сравниваются честно, без потери регистра знаков.
_NON_WORD = re.compile(r"[^\w\s]+", re.UNICODE)
_WS = re.compile(r"\s+")

# Плеер ждёт data-type="movie" или "series", а API отдаёт "movie"/"serial":
# маппим тип списка на тип тега, чтобы не отдавать SDK невалидное значение.
_API_TO_TAG_TYPE = {"movie": "movie", "serial": "series"}


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
        "player_id", "player_type",
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
    player_filled.
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
        "player_filled": 0,
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

        # player_id — внутренний ID видео из списка API (поле id): именно
        # его плеер ждёт в data-id тега. Тип маппим на значения SDK
        # (movie/series); заполняем только пустые поля.
        player_id = str(item.get("id") or "")
        if not title.player_id and player_id:
            changes["player_id"] = player_id
        embed_type = _API_TO_TAG_TYPE.get(item.get("type"))
        if not title.player_type and embed_type:
            changes["player_type"] = embed_type

        if not changes:
            continue

        if not dry_run:
            Title.objects.filter(pk=title.pk).update(**changes)
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
