"""
WebSocket consumer для real-time уведомлений и синхронизации контента.

Подключается по ws://host/ws/notifications/ и:
1. Подписывается на персональные уведомления пользователя
2. Подписывается на broadcast-группу обновлений контента
3. Получает мгновенные уведомления о новых фильмах, изменениях, удалениях
"""

import json

from channels.generic.websocket import AsyncWebsocketConsumer


class NotificationConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer для in-app уведомлений и real-time синхронизации."""

    async def connect(self):
        self.user = self.scope.get("user")
        if not self.user or not self.user.is_authenticated:
            await self.close()
            return

        # Персональная группа пользователя
        self.personal_group = f"notifications_{self.user.pk}"
        await self.channel_layer.group_add(self.personal_group, self.channel_name)

        # Broadcast группа для обновлений контента (все пользователи)
        self.content_group = "content_updates"
        await self.channel_layer.group_add(self.content_group, self.channel_name)

        await self.accept()

        await self.send(text_data=json.dumps({
            "type": "connection_established",
            "message": "Подключено к MovieHub",
        }))

    async def disconnect(self, close_code):
        if hasattr(self, "personal_group"):
            await self.channel_layer.group_discard(self.personal_group, self.channel_name)
        if hasattr(self, "content_group"):
            await self.channel_layer.group_discard(self.content_group, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """Обработка входящих сообщений от клиента."""
        pass

    async def send_notification(self, event):
        """Отправляет персональное уведомление клиенту."""
        await self.send(text_data=json.dumps({
            "type": "notification",
            "title": event.get("title", ""),
            "message": event.get("message", ""),
            "url": event.get("url", ""),
        }))

    async def content_update(self, event):
        """
        Отправляет broadcast об обновлении контента.

        Типы событий:
        - new_content: новый фильм/сериал опубликован
        - content_updated: фильм/сериал обновлён
        - content_deleted: фильм/сериал удалён
        - new_episode: новая серия сериала
        """
        await self.send(text_data=json.dumps({
            "type": "content_update",
            "event": event.get("event", ""),
            "title": event.get("title", ""),
            "url": event.get("url", ""),
        }))
