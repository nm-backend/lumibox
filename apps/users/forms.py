from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(
        label=_("Электронная почта"),
        widget=forms.EmailInput(
            attrs={"placeholder": "you@example.com", "autocomplete": "email"}
        ),
    )

    class Meta:
        model = User
        fields = ["email", "username"]
        labels = {"username": _("Имя пользователя")}
        help_texts = {
            "username": _("Это имя увидят рядом с вашими комментариями.")
        }

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(
                _("Пользователь с такой почтой уже зарегистрирован.")
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    username = forms.EmailField(
        label=_("Электронная почта"),
        widget=forms.EmailInput(
            attrs={"placeholder": "you@example.com", "autocomplete": "email"}
        ),
    )

    def clean_username(self):
        return self.cleaned_data["username"].lower()


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "bio", "avatar"]
        labels = {
            "username": _("Имя пользователя"),
            "bio": _("О себе"),
            "avatar": _("Аватар"),
        }
        widgets = {
            "bio": forms.Textarea(
                attrs={"rows": 4, "placeholder": _("Пара слов о себе")}
            ),
        }


class PlaybackSettingsForm(forms.ModelForm):
    """Настройки плеера пользователя."""

    class Meta:
        from apps.streaming.models import PlaybackPreference

        model = PlaybackPreference
        fields = ["autoplay_next", "default_quality", "default_speed", "subtitles_language"]
        labels = {
            "autoplay_next": _("Автовоспроизведение следующей серии"),
            "default_quality": _("Качество по умолчанию"),
            "default_speed": _("Скорость по умолчанию"),
            "subtitles_language": _("Язык субтитров по умолчанию"),
        }
