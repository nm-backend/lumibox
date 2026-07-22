"""
ASGI-точка входа. Понадобится, если проект будет обслуживать
асинхронные запросы или веб-сокеты.

Документация: https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

# Причина такого умолчания — та же, что и в wsgi.py: безопасность важнее удобства.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

application = get_asgi_application()
