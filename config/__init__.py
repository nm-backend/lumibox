"""
Пакет конфигурации проекта.

Импорт celery_app здесь обязателен: без него декоратор @shared_task
в приложениях не найдёт настроенное приложение Celery, когда Django
стартует через manage.py или wsgi.
"""

from config.celery import app as celery_app

__all__ = ["celery_app"]
