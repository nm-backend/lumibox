from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import View

from apps.catalog.models import Title
from apps.reviews.forms import CommentForm, ReviewForm
from apps.reviews.models import Comment, Review
from apps.reviews.services import save_comment, save_review


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
            # Ошибки показываем сообщением: страница фильма не перерисовывает
            # форму с ошибками, чтобы остаться простой.
            messages.error(request, "Проверьте оценку и текст отзыва.")
            return redirect(title.get_absolute_url() + "#reviews")

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
            messages.error(request, "Комментарий не может быть пустым.")
            return redirect(title.get_absolute_url() + "#comments")

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
