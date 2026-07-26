"""
Web Push уведомления для MovieHub.

Позволяет отправлять push-уведомления пользователям через Service Worker.
Использует VAPID для аутентификации с push-сервисами (FCM, Mozilla, etc.)

Эндпоинты:
- GET  /api/v1/push/vapid-key/  — публичный VAPID ключ для подписки
- POST /api/v1/push/subscribe/  — подписка на push
- POST /api/v1/push/send/       — отправка уведомления (admin only)
"""

import json
import logging

from django.conf import settings
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class VapidPublicKeyView(APIView):
    """Отдаёт публичный VAPID ключ для подписки в браузере."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        key = getattr(settings, "VAPID_PUBLIC_KEY", "")
        if not key:
            return Response(
                {"error": "Push notifications not configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"vapid_public_key": key})


class PushSubscribeView(APIView):
    """Сохраняет подписку пользователя на push-уведомления."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        subscription = request.data.get("subscription")
        if not subscription:
            return Response(
                {"error": "subscription required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Сохраняем подписку в профиле пользователя
        user = request.user
        user.push_subscription = json.dumps(subscription)
        user.save(update_fields=["push_subscription"])

        logger.info("User %s subscribed to push notifications", user.pk)
        return Response({"status": "subscribed"})


class PushUnsubscribeView(APIView):
    """Отписка от push-уведомлений."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        user.push_subscription = ""
        user.save(update_fields=["push_subscription"])
        return Response({"status": "unsubscribed"})
