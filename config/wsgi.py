"""
WSGI-точка входа. Через неё боевой сервер (Gunicorn) запускает Django.

Документация: https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

# По умолчанию — боевые настройки. Это сделано намеренно:
# если на сервере забудут задать переменную окружения, сайт запустится
# с выключенным DEBUG, а не покажет всем трассировки и содержимое настроек.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

application = get_wsgi_application()
