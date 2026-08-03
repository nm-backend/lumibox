from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView

from apps.library.models import Favorite, WatchHistory, Watchlist
from apps.reviews.models import Review
from apps.users.forms import LoginForm, ProfileForm, RegistrationForm


class RegisterView(CreateView):
    """
    Регистрация. После успеха сразу входим — лишний шаг никому не нужен.

    Ограничение частоты: не более 10 регистраций в час с одного IP.
    Без этого лимита злоумышленник за минуту заведёт тысячи аккаунтов.
    django-axes защищает только /login/, регистрация должна себя
    обезопасить самостоятельно.
    """

    form_class = RegistrationForm
    template_name = "users/register.html"
    success_url = reverse_lazy("catalog:home")

    def dispatch(self, request, *args, **kwargs):
        # Авторизованному регистрация не нужна — уводим на главную.
        if request.user.is_authenticated:
            return redirect("catalog:home")

        # Rate limiting: 10 регистраций в час с одного IP.
        # Ключ — IP адрес. Используем cache.get/set для совместимости
        # с любым бэкендом (не только Redis). Считаются только успешные
        # регистрации — простое открытие страницы лимит не тратит.
        if request.method == "POST":
            from django.core.cache import cache

            ip = request.META.get("REMOTE_ADDR", "unknown")
            cache_key = f"register:rate:{ip}"

            if cache.get(cache_key, 0) >= 10:
                # Именно 429 «слишком много запросов», а не 403: причина во
                # временном превышении лимита, и через час попытка пройдёт.
                # Раньше здесь ответ оборачивался в HttpResponseForbidden —
                # страница уходила бы телом чужого ответа с кодом 403, но до
                # этого не доходило: render не был импортирован и вьюха падала
                # с NameError, отдавая посетителю 500.
                return render(request, "429.html", status=429)

        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        from django.core.cache import cache

        ip = self.request.META.get("REMOTE_ADDR", "unknown")
        cache_key = f"register:rate:{ip}"
        cache.incr(cache_key) if cache.get(cache_key) else cache.set(cache_key, 1, 3600)
        login(self.request, self.object, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(self.request, f"Добро пожаловать, {self.object.display_name}!")
        return response


class UserLoginView(LoginView):
    """Вход по электронной почте."""

    form_class = LoginForm
    template_name = "users/login.html"
    redirect_authenticated_user = True


class UserLogoutView(LogoutView):
    """Выход. Только POST — иначе выйти можно было бы по чужой ссылке."""


class ProfileView(LoginRequiredMixin, UpdateView):
    """Профиль: сводка и редактирование."""

    form_class = ProfileForm
    template_name = "users/profile.html"
    success_url = reverse_lazy("users:profile")

    def get_object(self, queryset=None):
        # Правим всегда себя: номер пользователя из адреса не берём,
        # иначе можно было бы отредактировать чужой профиль.
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, "Профиль обновлён.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        context["favorites_count"] = Favorite.objects.for_user(user).count()
        context["watchlist_count"] = Watchlist.objects.for_user(user).count()
        context["history_count"] = WatchHistory.objects.for_user(user).count()
        context["reviews_count"] = Review.objects.filter(user=user).count()

        # Немного свежего избранного прямо в профиле — чтобы страница
        # не была пустой анкетой.
        context["recent_favorites"] = Favorite.objects.for_user(user).with_title()[:6]
        context["recent_watchlist"] = Watchlist.objects.for_user(user).with_title()[:6]
        return context
