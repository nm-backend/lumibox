from django.urls import path

from apps.library import views

app_name = "library"

urlpatterns = [
    path("favorites/", views.FavoriteListView.as_view(), name="favorites"),
    path("favorites/toggle/<slug:slug>/", views.ToggleFavoriteView.as_view(), name="toggle_favorite"),
    path("history/", views.WatchHistoryListView.as_view(), name="history"),
    path("history/clear/", views.ClearHistoryView.as_view(), name="clear_history"),
]
