from django.urls import reverse
from rest_framework import serializers

from apps.streaming.models import VideoAsset
from apps.streaming.services import get_playback_payload, save_watch_progress


class WatchProgressSerializer(serializers.Serializer):
    asset_id = serializers.UUIDField()
    position_seconds = serializers.IntegerField(min_value=0)
    is_completed = serializers.BooleanField(required=False, default=False)

    def validate_asset_id(self, value):
        try:
            return VideoAsset.objects.select_related("title", "episode__season__title").prefetch_related(
                "subtitle_tracks"
            ).get(pk=value)
        except VideoAsset.DoesNotExist as error:
            raise serializers.ValidationError("Видеоресурс не найден.") from error

    def create(self, validated_data):
        return save_watch_progress(
            user=self.context["request"].user,
            asset=validated_data["asset_id"],
            position_seconds=validated_data["position_seconds"],
            is_completed=validated_data["is_completed"],
        )


class WatchProgressResponseSerializer(serializers.Serializer):
    asset_id = serializers.UUIDField(source="video_asset_id")
    position_seconds = serializers.IntegerField()
    duration_seconds = serializers.IntegerField()
    is_completed = serializers.BooleanField()
    percentage = serializers.IntegerField()


class PlaybackConfigurationSerializer(serializers.Serializer):
    def to_representation(self, instance):
        request = self.context["request"]
        preference = self.context["preference"]
        return get_playback_payload(request, instance, preference)


class ContinueWatchingSerializer(serializers.Serializer):
    title = serializers.SerializerMethodField()
    episode = serializers.SerializerMethodField()
    watch_url = serializers.SerializerMethodField()
    progress_percent = serializers.IntegerField(source="percentage")
    position_seconds = serializers.IntegerField()
    duration_seconds = serializers.IntegerField()

    def get_title(self, progress):
        title = progress.video_asset.title_object
        return {"name": title.name, "slug": title.slug, "poster": title.poster.url if title.poster else None}

    def get_episode(self, progress):
        episode = progress.video_asset.episode
        if episode is None:
            return None
        return {
            "season": episode.season.number,
            "number": episode.number,
            "name": episode.name,
        }

    def get_watch_url(self, progress):
        episode = progress.video_asset.episode
        if episode:
            return episode.get_absolute_url()
        return reverse("streaming:watch_title", kwargs={"slug": progress.video_asset.title.slug})
