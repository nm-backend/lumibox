"""
Email верификация при регистрации.

Подход: при регистрации создаём токен, отправляем email с ссылкой.
Пользователь может пользоваться сайтом, но не может менять профиль
до подтверждения email. Через 48 часов неподтверждённый аккаунт деактивируется.
"""

from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


def send_verification_email(user, request):
    """Отправляет email для верификации."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    verify_url = request.build_absolute_uri(
        reverse("users:verify_email", kwargs={"uidb64": uid, "token": token})
    )

    subject = "Подтвердите email — MovieHub"
    message = render_to_string("users/verification_email.html", {
        "user": user,
        "verify_url": verify_url,
    })

    send_mail(subject, message, None, [user.email], fail_silently=True)
