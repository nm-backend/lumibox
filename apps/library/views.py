from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import ListView

from apps.catalog.models import Title
from apps.core.views import ElidedPaginationMixin
from apps.library.models import Favorite, WatchHistory, Watchlist
from apps.library.services import toggle_favorite, toggle_watchlist


def safe_next_url(request, title):
    """
    Куда вернуть пользователя после переключения.

    Принимает: запрос и запись каталога.
    Возвращает: безопасный адрес в пределах сайта.

    Значение next приходит из формы, то есть от клиента, и без проверки
    уводило бы на любой чужой домен. Сейчас это не эксплуатируется —
    подделать POST мешает CSRF, — но проверка стоит трёх строк и убирает
    целый класс ошибок: снимут CSRF или добавят вход по токену, и дыра
    оживёт. Ровно так же поступает LoginView самого Django.
    """
    next_url = request.POST.get("next")

    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url

    return title.get_absolute_url()


class ToggleFavoriteView(LoginRequiredMixin, View):
    """
    Переключает избранное. Работает и без JavaScript.

    Только POST: GET-запрос не должен менять данные — иначе поисковый робот,
    пройдя по ссылке, вычистит всё избранное пользователя.

    Если запрос пришёл от нашего скрипта (заголовок X-Requested-With),
    отвечаем JSON и страница не перезагружается. Обычная отправка формы
    возвращает пользователя назад — сайт работает с отключённым JS.
    """

    def post(self, request, slug):
        title = get_object_or_404(Title.objects.published(), slug=slug)
        is_favorite = toggle_favorite(request.user, title)

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"is_favorite": is_favorite})

        return redirect(safe_next_url(request, title))


class ToggleWatchlistView(LoginRequiredMixin, View):
    """
    Переключает «Смотреть позже». Зеркало ToggleFavoriteView:
    те же гарантии POST-только, JSON для скрипта, редирект без него.
    """

    def post(self, request, slug):
        title = get_object_or_404(Title.objects.published(), slug=slug)
        is_watchlist = toggle_watchlist(request.user, title)

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"is_watchlist": is_watchlist})

        return redirect(safe_next_url(request, title))


class FavoriteListView(LoginRequiredMixin, ElidedPaginationMixin, ListView):
    """Избранное пользователя."""

    template_name = "library/favorite_list.html"
    context_object_name = "favorites"
    paginate_by = 24

    def get_queryset(self):
        # Фильтр по статусу фильма обязателен: без него запись, которую
        # редактор снял с публикации, остаётся в избранном с постером и
        # ссылкой, ведущей на 404. Пользователь видит «битый» фильм.
        return (
            Favorite.objects.for_user(self.request.user)
            .filter(title__status=Title.Status.PUBLISHED)
            .with_title(self.request.user)
        )


class WatchlistListView(LoginRequiredMixin, ElidedPaginationMixin, ListView):
    """Список «Смотреть позже» пользователя."""

    template_name = "library/watchlist_list.html"
    context_object_name = "watchlist"
    paginate_by = 24

    def get_queryset(self):
        # Та же причина, что и в избранном: снятый с публикации фильм
        # не должен маячить ссылкой на 404.
        return (
            Watchlist.objects.for_user(self.request.user)
            .filter(title__status=Title.Status.PUBLISHED)
            .with_title(self.request.user)
        )


class WatchHistoryListView(LoginRequiredMixin, ElidedPaginationMixin, ListView):
    """История просмотров."""

    template_name = "library/history_list.html"
    context_object_name = "history"
    paginate_by = 24

    def get_queryset(self):
        # Та же причина, что и в избранном: снятый с публикации фильм
        # не должен маячить в истории ссылкой на 404.
        return (
            WatchHistory.objects.for_user(self.request.user)
            .filter(title__status=Title.Status.PUBLISHED)
            .with_title(self.request.user)
        )


class ClearHistoryView(LoginRequiredMixin, View):
    """Полная очистка истории просмотров."""

    def post(self, request):
        WatchHistory.objects.filter(user=request.user).delete()
        return redirect("library:history")
