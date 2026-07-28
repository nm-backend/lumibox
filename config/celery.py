"""
Приложение Celery.

Отдельный процесс, который выполняет долгие задачи вне запроса:
пересчёт рейтингов, рассылки, импорт данных. Пользователь не должен
ждать этого, пока грузится страница.

Запуск воркера:
    celery -A config worker -l info
Запуск планировщика:
    celery -A config beat -l info
"""

import os

from celery import Celery

# Celery запускается отдельным процессом и про manage.py ничего не знает,
# поэтому настройки указываем ему сами.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("lumibox")

# Все настройки берём из settings, префикс CELERY_ отбрасываем:
# CELERY_BROKER_URL становится broker_url.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Ищем tasks.py в каждом установленном приложении.
app.autodiscover_tasks()
