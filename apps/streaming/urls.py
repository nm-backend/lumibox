from django.urls import path

from apps.streaming import views

app_name = "streaming"

urlpatterns = [
    path("watch/<slug:slug>/", views.WatchTitleView.as_view(), name="watch_title"),
    path(
        "watch/<slug:slug>/season/<int:season_number>/episode/<int:episode_number>/",
        views.WatchEpisodeView.as_view(),
        name="watch_episode",
    ),
    path("watch/assets/<uuid:asset_id>/file/", views.LocalAssetFileView.as_view(), name="asset_file"),
    path("watch/assets/<uuid:asset_id>/download/", views.DownloadAssetView.as_view(), name="download"),
    path("watch/subtitles/<uuid:track_id>/", views.LocalSubtitleFileView.as_view(), name="subtitle_file"),
    path("api/v1/playback/progress/", views.PlaybackProgressApiView.as_view(), name="progress_api"),
    path(
        "api/v1/playback/assets/<uuid:asset_id>/",
        views.PlaybackConfigurationApiView.as_view(),
        name="configuration_api",
    ),
    path("api/v1/playback/continue-watching/", views.ContinueWatchingApiView.as_view(), name="continue_watching_api"),
]
