"""
Система уведомлений и real-time синхронизации.

Когда админ добавляет/изменяет/удаляет фильм — все подключённые
пользователи получают WebSocket уведомление с предложением обновить страницу.

Django messages — для синхронных уведомлений (при загрузке страницы).
WebSocket — для real-time уведомлений (мгновенно, без перезагрузки).
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)

# Группа для broadcast всем подключённым пользователям
BROADCAST_GROUP = "content_updates"


def _get_channel_layer():
    """Безопасно получает channel layer."""
    try:
        return get_channel_layer()
    except Exception:
        return None


def broadcast_content_update(event_type: str, title_name: str, url: str = ""):
    """
    Broadcast уведомления о контенте ВСЕМ подключённым пользователям.

    Используется когда админ добавляет/изменяет/удаляет фильм,
    чтобы все пользователи увидели обновление.
    """
    layer = _get_channel_layer()
    if layer is None:
        return

    try:
        async_to_sync(layer.group_send)(
            BROADCAST_GROUP,
            {
                "type": "content_update",
                "event": event_type,
                "title": title_name,
                "url": url,
            },
        )
    except Exception:
        logger.debug("Broadcast failed (channels not configured)")


def send_ws_notification(user_id: int, title: str, body: str, url: str = ""):
    """Отправляет WebSocket уведомление конкретному пользователю."""
    layer = _get_channel_layer()
    if layer is None:
        return

    try:
        async_to_sync(layer.group_send)(
            f"notifications_{user_id}",
            {
                "type": "send_notification",
                "title": title,
                "message": body,
                "url": url,
            },
        )
    except Exception:
        logger.debug("WebSocket notification failed (channels not configured)")


# ============================================================
# Функции для конкретных событий
# ============================================================


def notify_content_published(title):
    """Уведомляет ВСЕХ о публикации нового фильма/сериала."""
    broadcast_content_update(
        event_type="new_content",
        title_name=title.name,
        url=title.get_absolute_url(),
    )


def notify_content_updated(title):
    """Уведомляет ВСЕХ об обновлении фильма/сериала."""
    broadcast_content_update(
        event_type="content_updated",
        title_name=title.name,
        url=title.get_absolute_url(),
    )


def notify_content_deleted(title_name: str):
    """Уведомляет ВСЕХ об удалении фильма/сериала."""
    broadcast_content_update(
        event_type="content_deleted",
        title_name=title_name,
    )


def notify_new_episode(episode):
    """Уведомляет ВСЕХ о новом эпизоде сериала."""
    title_name = episode.season.title.name
    broadcast_content_update(
        event_type="new_episode",
        title_name=f"{title_name} — {episode.name}",
        url=episode.get_absolute_url(),
    )


def notify_new_review(review):
    """Уведомляет автора контента о новом отзыве."""
    title_name = review.title.name
    send_ws_notification(
        review.title.pk,  # Используем pk title как group key
        "Новый отзыв",
        f"Новый отзыв на «{title_name}»",
        review.title.get_absolute_url(),
    )


def notify_user_welcome(user):
    """Приветственное уведомление новому пользователю."""
    send_ws_notification(
        user.pk,
        "Добро пожаловать!",
        f"Привет, {user.display_name}! Добро пожаловать в MovieHub.",
        "/",
    )
