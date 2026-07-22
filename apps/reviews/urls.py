from django.urls import path

from apps.reviews import views

app_name = "reviews"

urlpatterns = [
    path("title/<slug:slug>/review/", views.ReviewCreateOrUpdateView.as_view(), name="save"),
    path("review/<int:pk>/delete/", views.ReviewDeleteView.as_view(), name="delete"),
]
