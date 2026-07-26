from django.urls import path

from apps.users import views

app_name = "users"

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.UserLoginView.as_view(), name="login"),
    path("logout/", views.UserLogoutView.as_view(), name="logout"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("password-reset/", views.UserPasswordResetView.as_view(), name="password_reset"),
    path("password-reset/done/", views.UserPasswordResetDoneView.as_view(), name="password_reset_done"),
    path(
        "password-reset/<uidb64>/<token>/",
        views.UserPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path("password-reset/complete/", views.UserPasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("verify/<uidb64>/<token>/", views.VerifyEmailView.as_view(), name="verify_email"),
]
