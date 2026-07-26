from django import forms
from django.utils.translation import gettext_lazy as _

from apps.reviews.models import MAX_RATING, MIN_RATING, Review


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["rating", "text"]
        widgets = {
            "rating": forms.Select(
                choices=[(value, value) for value in range(MIN_RATING, MAX_RATING + 1)]
            ),
            "text": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": _("Что вы думаете об этом фильме?"),
                }
            ),
        }
        labels = {
            "rating": _("Ваша оценка"),
            "text": _("Отзыв"),
        }
