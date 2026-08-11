from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.views.generic import View

from apps.catalog.models import Title
from apps.reviews.forms import CommentForm, ReviewForm
from apps.reviews.models import Comment, Review
from apps.reviews.services import save_comment, save_review


def render_title_page(request, title, **bound_forms):
    """
    Перерисовывает страницу фильма с формой, в которой остались ошибки.

    Раньше обе вьюхи при невалидной форме делали redirect с messages.error.
    Человек, написавший абзац отзыва и промахнувшийся с оценкой, возвращался
    на страницу с пустым полем: текст пропадал, а сообщение наверху не
    говорило, что именно не так. Сообщение об ошибке в форме умеет сказать
    это точнее, но для него форму нужно показать — то есть отрисовать
    страницу, а не увести с неё.

    Вьюху страницы вызываем напрямую, а не через as_view(): as_view() на
    POST ответил бы 405, а нам нужен именно её контекст — со всеми
    префетчами, серией для продолжения и списком комментариев.

    Импорт внутри функции: apps.catalog.views уже импортирует формы отзывов,
    и импорт на уровне модуля замкнул бы круг.
    """
    from apps.catalog.views import TitleDetailView

    view = TitleDetailView()
    view.setup(request, slug=title.slug)
    view.object = title
    for name, form in bound_forms.items():
        setattr(view, name, form)

    context = view.get_context_data(object=title)
    # 400, а не 200: страница отдаёт ту же разметку, но запрос не выполнен.
    return TemplateResponse(request, view.template_name, context, status=400)


class ReviewCreateOrUpdateView(LoginRequiredMixin, View):
    """
    Создаёт отзыв или обновляет существующий.

    Один пользователь — один отзыв на запись, поэтому отдельные «создать»
    и «изменить» не нужны: одна форма закрывает оба случая.
    """

    def post(self, request, slug):
        title = get_object_or_404(Title.objects.published(), slug=slug)

        # instance нужен форме, чтобы при правке она не ругалась на дубль.
        existing = Review.objects.filter(user=request.user, title=title).first()
        form = ReviewForm(request.POST, instance=existing)

        if not form.is_valid():
            return render_title_page(request, title, bound_review_form=form)

        # Сохраняет сервис, а не form.save(): между проверкой выше и вставкой
        # успевает пройти второй запрос, и он падает на ограничении базы.
        # Двойной отправки формы достаточно, чтобы поймать 500.
        save_review(
            user=request.user,
            title=title,
            rating=form.cleaned_data["rating"],
            text=form.cleaned_data["text"],
        )
        messages.success(request, "Отзыв сохранён.")

        return redirect(title.get_absolute_url() + "#reviews")


class ReviewDeleteView(LoginRequiredMixin, View):
    """Удаление своего отзыва."""

    def post(self, request, pk):
        # Фильтр по user обязателен: без него любой авторизованный
        # пользователь удалил бы чужой отзыв, подставив его номер.
        review = get_object_or_404(Review, pk=pk, user=request.user)
        title_url = review.title.get_absolute_url()
        review.delete()
        messages.success(request, "Отзыв удалён.")
        return redirect(title_url + "#reviews")


class CommentCreateView(LoginRequiredMixin, View):
    """
    Добавляет комментарий или ответ.

    Только POST: GET не должен менять данные. Черновик комментировать
    нельзя — запись ищем среди опубликованных.
    """

    def post(self, request, slug):
        title = get_object_or_404(Title.objects.published(), slug=slug)
        form = CommentForm(request.POST)

        if not form.is_valid():
            return render_title_page(request, title, bound_comment_form=form)

        # Родителя берём из POST, но обязательно сверяем с записью:
        # сам сервис отбросит чужого и схлопнет ответ на ответ.
        parent = None
        parent_id = request.POST.get("parent")
        if parent_id:
            parent = Comment.objects.published().filter(pk=parent_id).first()

        save_comment(
            user=request.user,
            title=title,
            text=form.cleaned_data["text"],
            parent=parent,
        )
        messages.success(request, "Комментарий добавлен.")
        return redirect(title.get_absolute_url() + "#comments")


class CommentDeleteView(LoginRequiredMixin, View):
    """Удаление своего комментария. Ответы уходят каскадом вместе с ним."""

    def post(self, request, pk):
        # Фильтр по user обязателен: без него любой вошедший удалил бы
        # чужой комментарий, подставив его номер.
        comment = get_object_or_404(Comment, pk=pk, user=request.user)
        title_url = comment.title.get_absolute_url()
        comment.delete()
        messages.success(request, "Комментарий удалён.")
        return redirect(title_url + "#comments")
