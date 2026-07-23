"""
Пакет конфигурации проекта.

Импорт celery_app здесь обязателен: без него декоратор @shared_task
в приложениях не найдёт настроенное приложение Celery, когда Django
стартует через manage.py или wsgi.
"""

import logging

logger = logging.getLogger(__name__)

try:
    from config.celery import app as celery_app

    __all__ = ["celery_app"]
except ImportError:
    # Celery может быть не установлен в окружении разработки.
    # Проект работает и без него: задачи выполняются синхронно
    # благодаря CELERY_TASK_ALWAYS_EAGER = True при отсутствии Redis.
    celery_app = None
    logger.info("Celery не установлен — фоновые задачи выполняются синхронно.")
    __all__ = []
