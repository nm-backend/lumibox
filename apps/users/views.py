from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView, LogoutView, PasswordResetConfirmView, PasswordResetView
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import CreateView, TemplateView, UpdateView

from apps.library.models import Favorite, WatchHistory
from apps.reviews.models import Review
from apps.streaming.models import PlaybackPreference
from apps.users.forms import LoginForm, PlaybackSettingsForm, ProfileForm, RegistrationForm


class RegisterView(CreateView):
    form_class = RegistrationForm
    template_name = "users/register.html"
    success_url = reverse_lazy("catalog:home")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("catalog:home")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(
            self.request,
            _("Добро пожаловать, %(name)s!") % {"name": self.object.display_name},
        )
        return response


class UserLoginView(LoginView):
    form_class = LoginForm
    template_name = "users/login.html"
    redirect_authenticated_user = True


class UserLogoutView(LogoutView):
    pass


class UserPasswordResetView(PasswordResetView):
    """Сброс пароля — отправляет email с ссылкой."""

    template_name = "users/password_reset.html"
    email_template_name = "users/password_reset_email.html"
    subject_template_name = "users/password_reset_subject.txt"
    success_url = reverse_lazy("users:password_reset_done")


class UserPasswordResetDoneView(TemplateView):
    """Подтверждение отправки письма."""

    template_name = "users/password_reset_done.html"


class UserPasswordResetConfirmView(PasswordResetConfirmView):
    """Ввод нового пароля по ссылке из письма."""

    template_name = "users/password_reset_confirm.html"
    success_url = reverse_lazy("users:password_reset_complete")


class UserPasswordResetCompleteView(TemplateView):
    """Подтверждение успешной смены пароля."""

    template_name = "users/password_reset_complete.html"


class VerifyEmailView(View):
    """Подтверждение email по ссылке из письма."""

    def get(self, request, uidb64, token):
        from django.contrib.auth import get_user_model
        from django.utils.http import urlsafe_base64_decode

        User = get_user_model()
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
        except (User.DoesNotExist, ValueError, OverflowError):
            user = None

        if user is not None and default_token_generator.check_token(user, token):
            user.is_active = True
            user.save(update_fields=["is_active"])
            messages.success(request, _("Email подтверждён. Спасибо!"))
            return redirect("users:login")

        messages.error(request, _("Ссылка недействительна или устарела."))
        return redirect("users:register")


class ProfileView(LoginRequiredMixin, UpdateView):
    form_class = ProfileForm
    template_name = "users/profile.html"
    success_url = reverse_lazy("users:profile")

    def post(self, request, *args, **kwargs):
        # Обработка смены пароля отдельной формой
        if "change_password" in request.POST:
            from django.contrib.auth import update_session_auth_hash
            from django.contrib.auth.forms import PasswordChangeForm

            pw_form = PasswordChangeForm(request.user, request.POST)
            if pw_form.is_valid():
                user = pw_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, _("Пароль успешно изменён."))
            else:
                for error in pw_form.errors.values():
                    messages.error(request, error[0])
            return redirect("users:profile")

        return super().post(request, *args, **kwargs)

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, _("Профиль обновлён."))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["favorites_count"] = Favorite.objects.for_user(user).count()
        context["history_count"] = WatchHistory.objects.for_user(user).count()
        context["reviews_count"] = Review.objects.filter(user=user).count()
        context["recent_favorites"] = (
            Favorite.objects.for_user(user).with_title()[:6]
        )
        return context


class SettingsView(LoginRequiredMixin, UpdateView):
    """Настройки плеера пользователя."""

    form_class = PlaybackSettingsForm
    template_name = "users/settings.html"
    success_url = reverse_lazy("users:settings")

    def get_object(self, queryset=None):
        obj, _ = PlaybackPreference.objects.get_or_create(user=self.request.user)
        return obj

    def form_valid(self, form):
        messages.success(self.request, _("Настройки сохранены."))
        return super().form_valid(form)
