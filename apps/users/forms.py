from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

User = get_user_model()


class RegistrationForm(UserCreationForm):
    """
    Регистрация нового пользователя.

    Наследуемся от UserCreationForm, а не пишем с нуля: она уже умеет
    сверять два пароля и прогонять их через валидаторы Django.
    Нам остаётся добавить почту и подписи.
    """

    email = forms.EmailField(
        label="Электронная почта",
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com", "autocomplete": "email"}),
    )

    class Meta:
        model = User
        fields = ["email", "username"]
        labels = {"username": "Имя пользователя"}
        help_texts = {"username": "Это имя увидят рядом с вашими комментариями."}

    def clean_email(self):
        # Приводим почту к нижнему регистру: иначе Ivan@mail.ru и ivan@mail.ru
        # станут разными аккаунтами, хотя это один и тот же адрес.
        email = self.cleaned_data["email"].lower()

        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Пользователь с такой почтой уже зарегистрирован.")

        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    """Вход по почте. Переопределяем только подписи и подсказки браузеру."""

    username = forms.EmailField(
        label="Электронная почта",
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com", "autocomplete": "email"}),
    )

    def clean_username(self):
        return self.cleaned_data["username"].lower()


class ProfileForm(forms.ModelForm):
    """Редактирование профиля."""

    class Meta:
        model = User
        fields = ["username", "bio", "avatar"]
        labels = {
            "username": "Имя пользователя",
            "bio": "О себе",
            "avatar": "Аватар",
        }
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 4, "placeholder": "Пара слов о себе"}),
        }
