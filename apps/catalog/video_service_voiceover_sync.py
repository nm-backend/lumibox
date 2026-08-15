"""
Сопоставление озвучек каталога с озвучками внешнего видеосервиса.

Внешний плеер умеет показывать конкретную озвучку (data-voiceover),
но ID озвучек у сервиса свои. Команда sync_voiceovers тянет список
из API (GET /videos/voiceovers) и проставляет vibix_voiceover_id
озвучкам каталога по совпадению нормализованного названия.

Правила, чтобы не наставить чужих ID:

- Заполняем только пустые поля: вручную введённый ID не затирается.
- Одна озвучка сервиса может сопоставиться нескольким озвучкам каталога
  с одинаковым названием (варианты написания) — это нормально, плеер
  получит тот же ID.
"""

from django.utils.text import slugify

from apps.catalog.models import VoiceOver
from apps.catalog.video_service_api import (
    VideoServiceAPIError,
    fetch_voiceovers,
    get_vibix_api_token,
)
from apps.catalog.video_service_sync import normalize_name


def _unique_slug(name):
    """
    Свободный адрес для новой озвучки.

    slugify кириллицы даёт пустую строку, а два разных названия могут дать
    один адрес — в обоих случаях запись не создалась бы. Добавляем числовой
    хвост, пока адрес не окажется свободным.
    """
    base = slugify(name, allow_unicode=False) or "voiceover"
    slug, suffix = base, 2
    while VoiceOver.objects.filter(slug=slug).exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def import_voiceovers_from_service(*, dry_run=False):
    """
    Создаёт недостающие озвучки каталога из справочника сервиса.

    Справочник озвучек каталога обычно пуст, а без записей не заполнится
    и data-voiceover внешнего плеера. Команда import_voiceovers тянет
    GET /videos/voiceovers и заводит недостающие озвучки, сразу с
    vibix_voiceover_id. Существующие записи не дублируются (поиск по
    названию), а уже введённый вручную ID не затирается.

    dry_run=True ничего не пишет в базу. Возвращает словарь счётчиков:
    fetched (озвучек от сервиса), created (созданных), filled (заполненных
    у существующих).
    """
    api_key = get_vibix_api_token()
    if not api_key:
        raise VideoServiceAPIError(
            "VIDEO_SERVICE_API_KEY не задан — синхронизацию невозможно запустить"
        )

    items = fetch_voiceovers(api_key)
    stats = {"fetched": len(items), "created": 0, "filled": 0}
    for item in items:
        name = str(item.get("name") or "").strip()
        service_id = item.get("id")
        if not name or not service_id:
            continue
        existing = VoiceOver.objects.filter(name__iexact=name).first()
        if existing is None:
            stats["created"] += 1
            if not dry_run:
                VoiceOver.objects.create(
                    name=name,
                    slug=_unique_slug(name),
                    vibix_voiceover_id=service_id,
                )
            continue
        if existing.vibix_voiceover_id is None:
            stats["filled"] += 1
            if not dry_run:
                VoiceOver.objects.filter(pk=existing.pk).update(
                    vibix_voiceover_id=service_id
                )
    return stats


def sync_voiceover_ids(*, dry_run=False):
    """
    Прогоняет сопоставление озвучек и возвращает статистику.

    dry_run=True ничего не пишет в базу. Возвращает словарь счётчиков:
    fetched (озвучек от сервиса), filled (заполненных сопоставлений).
    """
    api_key = get_vibix_api_token()
    if not api_key:
        raise VideoServiceAPIError(
            "VIDEO_SERVICE_API_KEY не задан — синхронизацию невозможно запустить"
        )

    items = fetch_voiceovers(api_key)

    # Индекс по нормализованному названию: одна озвучка каталога —
    # один кандидат на ID сервиса.
    index = {}
    for voiceover in VoiceOver.objects.all().only(
        "pk", "name", "vibix_voiceover_id"
    ):
        norm = normalize_name(voiceover.name)
        if not norm:
            continue
        index.setdefault(norm, []).append(voiceover)

    stats = {"fetched": len(items), "filled": 0}
    for item in items:
        voiceover_id = item.get("id")
        if not voiceover_id:
            continue
        for voiceover in index.get(normalize_name(item.get("name") or ""), []):
            if voiceover.vibix_voiceover_id:
                continue
            if not dry_run:
                VoiceOver.objects.filter(pk=voiceover.pk).update(
                    vibix_voiceover_id=voiceover_id
                )
            stats["filled"] += 1
    return stats
