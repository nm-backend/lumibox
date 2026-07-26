"""
Контекстные процессоры MovieHub.

Добавляют переменные в контекст всех шаблонов.
"""

from django.conf import settings


def analytics_ids(request):
    """Передаёт ID аналитики в шаблоны."""
    return {
        "GOOGLE_ANALYTICS_ID": getattr(settings, "GOOGLE_ANALYTICS_ID", ""),
        "YANDEX_METRIKA_ID": getattr(settings, "YANDEX_METRIKA_ID", ""),
    }
