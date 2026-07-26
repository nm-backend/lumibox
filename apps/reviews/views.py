from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import View

from apps.catalog.models import Title
from apps.reviews.forms import ReviewForm
from apps.reviews.models import Review
from apps.reviews.services import save_review


class ReviewCreateOrUpdateView(LoginRequiredMixin, View):
    def post(self, request, slug):
        title = get_object_or_404(Title.objects.published(), slug=slug)

        existing = Review.objects.filter(user=request.user, title=title).first()
        form = ReviewForm(request.POST, instance=existing)

        if not form.is_valid():
            messages.error(request, _("Проверьте оценку и текст отзыва."))
            return redirect(title.get_absolute_url() + "#reviews")

        save_review(
            user=request.user,
            title=title,
            rating=form.cleaned_data["rating"],
            text=form.cleaned_data["text"],
        )
        messages.success(request, _("Отзыв сохранён."))
        return redirect(title.get_absolute_url() + "#reviews")


class ReviewDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        review = get_object_or_404(Review, pk=pk, user=request.user)
        title_url = review.title.get_absolute_url()
        review.delete()
        messages.success(request, _("Отзыв удалён."))
        return redirect(title_url + "#reviews")
