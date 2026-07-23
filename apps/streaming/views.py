import mimetypes

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import TemplateView
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Title
from apps.streaming.models import Episode, SubtitleTrack, VideoAsset
from apps.streaming.serializers import (
    ContinueWatchingSerializer,
    PlaybackConfigurationSerializer,
    WatchProgressResponseSerializer,
    WatchProgressSerializer,
)
from apps.streaming.services import (
    PlaybackUnavailable,
    get_continue_watching,
    get_download_url,
    get_playback_payload,
    get_preference,
    require_playback_access,
)


class PlaybackMixin(TemplateView):
    template_name = "streaming/player.html"

    def render_asset(self, request, asset: VideoAsset):
        require_playback_access(request.user, asset)
        try:
            player_config = get_playback_payload(request, asset, get_preference(request.user))
        except PlaybackUnavailable as error:
            raise Http404(str(error)) from error
        return self.render_to_response(
            self.get_context_data(
                asset=asset,
                title=asset.title_object,
                episode=asset.episode,
                player_config=player_config,
            )
        )


class WatchTitleView(PlaybackMixin):
    """Точка входа для фильма и продолжения сериала с первой доступной серии."""

    def get(self, request, slug):
        title = get_object_or_404(Title.objects.published(), slug=slug)
        if title.type == Title.Type.SERIES:
            episode = (
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
            if episode is None:
                raise Http404("Для сериала пока нет доступных серий.")
            return redirect(episode.get_absolute_url())

        asset = get_object_or_404(
            VideoAsset.objects.filter(title=title, status=VideoAsset.Status.READY)
            .select_related("title")
            .prefetch_related("subtitle_tracks"),
        )
        return self.render_asset(request, asset)


class WatchEpisodeView(PlaybackMixin):
    def get(self, request, slug, season_number, episode_number):
        asset = get_object_or_404(
            VideoAsset.objects.filter(
                episode__season__title__slug=slug,
                episode__season__number=season_number,
                episode__number=episode_number,
                episode__season__title__status=Title.Status.PUBLISHED,
                episode__season__is_published=True,
                episode__is_published=True,
                status=VideoAsset.Status.READY,
            )
            .select_related("episode__season__title")
            .prefetch_related("subtitle_tracks"),
        )
        return self.render_asset(request, asset)


class LocalAssetFileView(View):
    """Защищённая отдача локального файла только после проверки доступа."""

    def get(self, request, asset_id):
        asset = get_object_or_404(
            VideoAsset.objects.select_related("title", "episode__season__title"),
            pk=asset_id,
            provider=VideoAsset.Provider.LOCAL,
        )
        require_playback_access(request.user, asset)
        if not asset.media_file:
            raise Http404("Файл видеоресурса не найден.")
        content_type, _ = mimetypes.guess_type(asset.media_file.name)
        return FileResponse(asset.media_file.open("rb"), content_type=content_type or "application/octet-stream")


class LocalSubtitleFileView(View):
    def get(self, request, track_id):
        track = get_object_or_404(
            SubtitleTrack.objects.select_related("video_asset__title", "video_asset__episode__season__title"),
            pk=track_id,
        )
        require_playback_access(request.user, track.video_asset)
        if not track.subtitle_file:
            raise Http404("Файл субтитров не найден.")
        content_type, _ = mimetypes.guess_type(track.subtitle_file.name)
        return FileResponse(track.subtitle_file.open("rb"), content_type=content_type or "text/vtt")


class DownloadAssetView(LoginRequiredMixin, View):
    """Скачивание работает только при разрешении в лицензированном видеоресурсе."""

    def get(self, request, asset_id):
        asset = get_object_or_404(
            VideoAsset.objects.select_related("title", "episode__season__title"),
            pk=asset_id,
            allow_download=True,
        )
        require_playback_access(request.user, asset)
        if asset.provider == VideoAsset.Provider.LOCAL:
            if not asset.media_file:
                raise Http404("Файл видеоресурса не найден.")
            content_type, _ = mimetypes.guess_type(asset.media_file.name)
            return FileResponse(
                asset.media_file.open("rb"),
                as_attachment=True,
                filename=asset.display_download_name,
                content_type=content_type or "application/octet-stream",
            )
        try:
            return HttpResponseRedirect(get_download_url(asset))
        except PlaybackUnavailable as error:
            raise Http404(str(error)) from error


class PlaybackProgressApiView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=WatchProgressSerializer, responses={200: WatchProgressResponseSerializer})
    def post(self, request):
        serializer = WatchProgressSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        progress = serializer.save()
        return Response(WatchProgressResponseSerializer(progress).data, status=status.HTTP_200_OK)


class PlaybackConfigurationApiView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=PlaybackConfigurationSerializer)
    def get(self, request, asset_id):
        asset = get_object_or_404(
            VideoAsset.objects.select_related("title", "episode__season__title").prefetch_related("subtitle_tracks"),
            pk=asset_id,
        )
        require_playback_access(request.user, asset)
        preference = get_preference(request.user)
        serializer = PlaybackConfigurationSerializer(
            asset, context={"request": request, "preference": preference}
        )
        return Response(serializer.data)


class ContinueWatchingApiView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=ContinueWatchingSerializer(many=True))
    def get(self, request):
        return Response(ContinueWatchingSerializer(get_continue_watching(request.user), many=True).data)
