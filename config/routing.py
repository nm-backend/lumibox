"""
WebSocket routing для Django Channels.

Определяет маршруты для WebSocket подключений.
"""

from django.urls import re_path

from apps.core.consumers import NotificationConsumer

websocket_urlpatterns = [
    re_path(r"ws/notifications/$", NotificationConsumer.as_asgi()),
]
