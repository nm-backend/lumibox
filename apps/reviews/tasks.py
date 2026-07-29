"""
Celery tasks: cache warming for high-traffic pages.

Tasks moved to apps.catalog.tasks (where the cache logic lives).
These imports remain for backward compatibility with existing Celery Beat
schedules that may still reference apps.reviews.tasks.*
"""
from apps.catalog.tasks import warm_home_cache, warm_reference_caches  # noqa: F401
