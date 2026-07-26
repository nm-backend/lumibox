"""
Настройки для локальной разработки.

Здесь всё, что удобно программисту, но недопустимо на боевом сервере.
"""

# Звёздочка здесь оправдана: это общепринятый способ разделения настроек Django.
# Мы забираем всю базовую конфигурацию и переопределяем только нужное.
from .base import *  # noqa: F401,F403

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Письма не отправляем по-настоящему, а печатаем в консоль.
# Пригодится на этапе регистрации — не нужен почтовый сервер.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Демо-URL для видеостриминга: Apple HLS sample stream.
# Позволяет плееру работать локально без реального Cloudflare Stream.
# В продакшене настройки берутся из переменных окружения.
STREAMING_PROVIDER_CONFIG = {
    "cloudflare_stream": {
        "delivery_base_url": "https://devstreaming-cdn.apple.com",
    },
    "cloudflare_r2": {"delivery_base_url": ""},
    "aws_s3": {"delivery_base_url": ""},
    "backblaze_b2": {"delivery_base_url": ""},
    "minio": {"delivery_base_url": ""},
}
