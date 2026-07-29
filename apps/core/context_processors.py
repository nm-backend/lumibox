from django.conf import settings


def global_settings(request):
    """Глобальные переменные для всех шаблонов.

    Добавляет в контекст шаблонов настройки, которые должны быть
    доступны на каждой странице: Google Analytics ID, флаги фич.
    """
    return {
        "ga_measurement_id": getattr(settings, "GA_MEASUREMENT_ID", ""),
    }
