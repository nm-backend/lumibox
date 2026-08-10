from django.urls import path

from apps.reviews import views

app_name = "reviews"

urlpatterns = [
    path("title/<slug:slug>/review/", views.ReviewCreateOrUpdateView.as_view(), name="save"),
    path("review/<int:pk>/delete/", views.ReviewDeleteView.as_view(), name="delete"),
    path("title/<slug:slug>/comment/", views.CommentCreateView.as_view(), name="comment_add"),
    path("comment/<int:pk>/delete/", views.CommentDeleteView.as_view(), name="comment_delete"),
]
