"""
Настройки для боевого сервера.

Закрывают требования раздела 7 ТЗ: HTTPS, защита cookie, защита от XSS
и clickjacking. Эти настройки нельзя включать локально — без сертификата
браузер просто не откроет сайт.
"""

from .base import *  # noqa: F401,F403

DEBUG = False

# Домены задаются переменной окружения — в коде их нет.
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")  # noqa: F405

# Render (и другие PaaS) сообщают собственный домен *.onrender.com отдельной
# переменной. Добавляем его сами, чтобы сайт открылся сразу после деплоя,
# ещё до того как владелец подключит свой домен.
RENDER_HOST = env("RENDER_EXTERNAL_HOSTNAME", default="")  # noqa: F405
if RENDER_HOST:
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, RENDER_HOST]

# CSRF за HTTPS-прокси: Django сверяет Origin входящего POST с этим списком.
# Без схемы https:// вход в админку на боевом домене падал бы с ошибкой CSRF.
# Звёздочки и localhost сюда не берём — origin должен быть конкретным.
CSRF_TRUSTED_ORIGINS = [
    f"https://{host}"
    for host in ALLOWED_HOSTS
    if host not in ("localhost", "127.0.0.1") and "*" not in host
]

# Health-check не должен попадать под SSL-redirect: платформа опрашивает его
# по внутреннему HTTP, и ответ-редирект 301 читался бы как «сервис недоступен».
SECURE_REDIRECT_EXEMPT = [r"^healthz/?$"]


# Отдача статики самим приложением. Идёт сразу после SecurityMiddleware —
# так требует whitenoise. Когда перед Django встанет Nginx, статику
# быстрее отдаст он, и эту строку можно будет убрать.
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")  # noqa: F405

# Обязателен ли R2 для продакшена — проверяем по наличию бакета.
# Если R2 не настроен, работаем на локальной файловой системе (эфимерной на Render).
_USE_R2 = bool(env("AWS_STORAGE_BUCKET_NAME", default=""))

if _USE_R2:
    STORAGES = {
        "default": {
            # Cloudflare R2 — S3-совместимое объектное хранилище.
            # Файлы не теряются при перезапуске, в отличие от локального диска.
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "access_key": env("AWS_ACCESS_KEY_ID"),
                "secret_key": env("AWS_SECRET_ACCESS_KEY"),
                "bucket_name": env("AWS_STORAGE_BUCKET_NAME"),
                "region_name": env("AWS_S3_REGION_NAME", default="auto"),
                "endpoint_url": env("AWS_S3_ENDPOINT_URL"),
                # Публичный URL (cloudfront.net, R2.dev, свой домен).
                # Если не задан, Django строит URL из endpoint_url + bucket_name.
                "custom_domain": env("CLOUDFLARE_R2_PUBLIC_URL", default="") or None,
                # Загружаемые файлы доступны всем — так постеры и видео показываются
                # в браузере без подписанных URL.
                "default_acl": "public-read",
                "signature_version": "s3v4",
                # Не перезаписывать файлы — каждый новый файл получает уникальное имя.
                "file_overwrite": False,
            },
        },
        "staticfiles": {
            # Статика по-прежнему отдаётся через whitenoise из контейнера.
            # Не кладём её в R2 — так быстрее: не нужен лишний HTTP к R2 на каждый CSS.
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
else:
    # R2 не настроен — локальный диск.
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }


# Весь трафик переводим на HTTPS.
SECURE_SSL_REDIRECT = True

# Nginx принимает HTTPS и ходит в Django по HTTP.
# Этот заголовок объясняет Django, что исходный запрос всё-таки был защищённым.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Cookie сессии и CSRF отдаём только по HTTPS, чтобы их нельзя было перехватить.
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# HSTS: браузер год не будет даже пытаться зайти по HTTP.
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Запрещаем браузеру угадывать тип файла — защита от подмены содержимого.
SECURE_CONTENT_TYPE_NOSNIFF = True

# Запрещаем показывать сайт внутри чужого iframe — защита от clickjacking.
X_FRAME_OPTIONS = "DENY"

# Referrer-Policy: не передаём URL страницы на внешние сайты.
SECURE_REFERRER_POLICY = "same-origin"

# Cookie CSRF и сессии — только HTTP (не читаются из JavaScript).
# CSRF_COOKIE_SAMESITE = 'Lax' уже проставлен по умолчанию в Django.
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True

# Сессия живёт 2 недели (явное указание вместо умолчания).
SESSION_COOKIE_AGE = 1209600  # 14 дней
SESSION_SAVE_EVERY_REQUEST = False
SESSION_EXPIRE_AT_BROWSER_CLOSE = False


# Content-Security-Policy: защита от XSS и инжекции.
# Разрешаем скрипты и стили только с собственного домена.
# unsafe-inline для стилей нужен, так как Django-админка и некоторые
# плагины используют инлайновые стили.
MIDDLEWARE += [  # noqa: F405
    "apps.core.middleware.ContentSecurityPolicyMiddleware",
]
