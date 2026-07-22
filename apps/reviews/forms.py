from django import forms

from apps.reviews.models import MAX_RATING, MIN_RATING, Review


class ReviewForm(forms.ModelForm):
    """Форма отзыва. Используется и для создания, и для редактирования."""

    class Meta:
        model = Review
        fields = ["rating", "text"]
        widgets = {
            # Выпадающий список от 1 до 10: проще звёздочек на JavaScript
            # и работает везде, включая скринридеры.
            "rating": forms.Select(choices=[(value, value) for value in range(MIN_RATING, MAX_RATING + 1)]),
            "text": forms.Textarea(attrs={"rows": 4, "placeholder": "Что вы думаете об этом фильме?"}),
        }
        labels = {"rating": "Ваша оценка", "text": "Отзыв"}
