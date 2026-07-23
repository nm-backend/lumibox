"""Правила доступа и адаптеры доставки лицензированного видеоконтента."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Title
from apps.library.services import remember_view
from apps.streaming.models import Episode, PlaybackPreference, SubtitleTrack, VideoAsset, WatchProgress


MINIMUM_RESUME_SECONDS = 30


class PlaybackUnavailable(Exception):
    """Провайдер пока не настроен для доставки ресурса."""


@dataclass(frozen=True)
class PlaybackSource:
    url: str
    stream_type: str


def has_playback_access(user: Any, asset: VideoAsset) -> bool:
    """Проверяет публикацию, лицензию и будущий коммерческий уровень доступа."""
    if not asset.is_available or not _is_content_published(asset):
        return False

    if asset.access_level == VideoAsset.AccessLevel.FREE:
        return True

    # Редактору нужен предпросмотр до подключения расчётов с платёжным провайдером.
    if getattr(user, "is_staff", False):
        return True

    # Платный доступ намеренно закрыт до появления реального entitlement-провайдера.
    # Это безопаснее «демонстрационной оплаты», которая открывала бы Premium всем.
    return False


def require_playback_access(user: Any, asset: VideoAsset) -> None:
    if not has_playback_access(user, asset):
        raise PermissionDenied("Этот контент недоступен для текущего профиля или лицензии.")


def get_playback_payload(request: Any, asset: VideoAsset, preference: PlaybackPreference | None) -> dict[str, Any]:
    """Строит безопасную конфигурацию, потребляемую веб-плеером."""
    source = get_playback_source(asset)
    subtitle_tracks = [
        {
            "id": str(track.pk),
            "language": track.language_code,
            "label": track.label,
            "kind": track.kind,
            "default": track.is_default,
            "url": get_subtitle_url(track),
        }
        for track in asset.subtitle_tracks.all()
    ]
    episode = asset.episode
    next_episode = get_next_episode(episode) if episode else None
    progress = get_progress(request.user, asset) if request.user.is_authenticated else None

    return {
        "assetId": str(asset.pk),
        "source": {"url": source.url, "type": source.stream_type},
        "duration": asset.duration_seconds,
        "qualities": asset.available_qualities or ["auto"],
        "subtitleTracks": subtitle_tracks,
        "resumeAt": progress.position_seconds if progress and not progress.is_completed else 0,
        "autoplayNext": preference.autoplay_next if preference else True,
        "defaultQuality": preference.default_quality if preference else PlaybackPreference.Quality.AUTO,
        "defaultSpeed": float(preference.default_speed) if preference else 1,
        "subtitlesLanguage": preference.subtitles_language if preference else "",
        "intro": _episode_marker(episode, "intro_start_seconds", "intro_end_seconds"),
        "recap": _episode_marker(episode, "recap_start_seconds", "recap_end_seconds"),
        "nextEpisode": {
            "title": next_episode.name,
            "url": next_episode.get_absolute_url(),
        }
        if next_episode
        else None,
        "progressUrl": reverse("streaming:progress_api") if request.user.is_authenticated else None,
        "downloadUrl": reverse("streaming:download", kwargs={"asset_id": asset.pk})
        if asset.allow_download and request.user.is_authenticated
        else None,
    }


def get_playback_source(asset: VideoAsset) -> PlaybackSource:
    """Возвращает источник исключительно от разрешённого storage provider."""
    if asset.provider == VideoAsset.Provider.LOCAL:
        if not asset.media_file:
            raise PlaybackUnavailable("Для локального видеоресурса не загружен файл.")
        return PlaybackSource(
            url=reverse("streaming:asset_file", kwargs={"asset_id": asset.pk}),
            stream_type=asset.stream_type,
        )

    return PlaybackSource(url=_get_provider_url(asset.provider, asset.asset_key), stream_type=asset.stream_type)


def get_download_url(asset: VideoAsset) -> str:
    """Строит URL загрузки для внешнего provider без клиентских URL в базе."""
    if asset.provider == VideoAsset.Provider.LOCAL:
        return reverse("streaming:download", kwargs={"asset_id": asset.pk})
    return _get_provider_url(asset.provider, asset.asset_key, purpose="download")


def get_subtitle_url(track: SubtitleTrack) -> str:
    if track.video_asset.provider == VideoAsset.Provider.LOCAL:
        return reverse("streaming:subtitle_file", kwargs={"track_id": track.pk})
    return _get_provider_url(track.video_asset.provider, track.storage_key)


def get_preference(user: Any) -> PlaybackPreference | None:
    if not user.is_authenticated:
        return None
    preference, _ = PlaybackPreference.objects.get_or_create(user=user)
    return preference


def save_watch_progress(
    *,
    user: Any,
    asset: VideoAsset,
    position_seconds: int,
    is_completed: bool = False,
) -> WatchProgress:
    """Сохраняет нормализованную позицию и не доверяет длительности от клиента."""
    require_playback_access(user, asset)
    normalized_position = max(0, min(int(position_seconds), asset.duration_seconds))
    completed = is_completed or _is_near_completion(normalized_position, asset.duration_seconds)
    if completed:
        normalized_position = asset.duration_seconds

    with transaction.atomic():
        progress, _ = WatchProgress.objects.update_or_create(
            user=user,
            video_asset=asset,
            defaults={
                "position_seconds": normalized_position,
                "duration_seconds": asset.duration_seconds,
                "is_completed": completed,
            },
        )
        remember_view(user, asset.title_object)
    return progress


def get_progress(user: Any, asset: VideoAsset) -> WatchProgress | None:
    if not user.is_authenticated:
        return None
    return WatchProgress.objects.filter(user=user, video_asset=asset).first()


def get_continue_watching(user: Any, limit: int = 12):
    """Возвращает только незавершённые лицензированные просмотры с нужными связями."""
    if not user.is_authenticated:
        return WatchProgress.objects.none()

    published_content = Q(video_asset__title__status=Title.Status.PUBLISHED) | Q(
        video_asset__episode__is_published=True,
        video_asset__episode__season__is_published=True,
        video_asset__episode__season__title__status=Title.Status.PUBLISHED,
    )
    return (
        WatchProgress.objects.filter(
            user=user,
            is_completed=False,
            position_seconds__gte=MINIMUM_RESUME_SECONDS,
            video_asset__status=VideoAsset.Status.READY,
        )
        .filter(published_content)
        .select_related("video_asset__title", "video_asset__episode__season__title")
        .prefetch_related("video_asset__title__genres", "video_asset__episode__season__title__genres")
        .order_by("-last_watched_at")[:limit]
    )


def get_next_episode(episode: Episode | None) -> Episode | None:
    if episode is None:
        return None
    return (
        Episode.objects.filter(
            season__title=episode.season.title,
            season__is_published=True,
            is_published=True,
            video_asset__status=VideoAsset.Status.READY,
        )
        .filter(
            Q(season__number__gt=episode.season.number)
            | Q(season__number=episode.season.number, number__gt=episode.number)
        )
        .select_related("season__title")
        .order_by("season__number", "number")
        .first()
    )


def get_watch_url(title: Title) -> str | None:
    """Находит точку входа в просмотр фильма или первого доступного эпизода."""
    if title.type == Title.Type.MOVIE:
        if VideoAsset.objects.filter(title=title, status=VideoAsset.Status.READY).exists():
            return reverse("streaming:watch_title", kwargs={"slug": title.slug})
        return None

    first_episode = (
        Episode.objects.filter(
            season__title=title,
            season__is_published=True,
            is_published=True,
            video_asset__status=VideoAsset.Status.READY,
        )
        .select_related("season")
        .order_by("season__number", "number")
        .first()
    )
    return first_episode.get_absolute_url() if first_episode else None


def _get_provider_url(provider: str, asset_key: str, purpose: str = "playback") -> str:
    config = getattr(settings, "STREAMING_PROVIDER_CONFIG", {}).get(provider, {})
    base_url = config.get(f"{purpose}_base_url") or config.get("delivery_base_url")
    if not base_url:
        raise PlaybackUnavailable(f"Провайдер {provider!r} не настроен для {purpose}.")
    return f"{base_url.rstrip('/')}/{quote(asset_key, safe='/')}"


def _is_content_published(asset: VideoAsset) -> bool:
    if asset.episode_id:
        return bool(
            asset.episode.is_published
            and asset.episode.season.is_published
            and asset.episode.season.title.status == Title.Status.PUBLISHED
        )
    return bool(asset.title and asset.title.status == Title.Status.PUBLISHED)


def _episode_marker(episode: Episode | None, start_field: str, end_field: str) -> dict[str, int] | None:
    if episode is None:
        return None
    start = getattr(episode, start_field)
    end = getattr(episode, end_field)
    return {"start": start, "end": end} if start is not None and end is not None else None


def _is_near_completion(position: int, duration: int) -> bool:
    return position >= duration - max(30, round(duration * 0.05))
