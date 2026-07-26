"""
Базовые настройки MovieHub.

Здесь лежит только то, что одинаково для всех окружений.
Всё, что различается (отладка, домены, безопасность), находится
в development.py и production.py — они импортируют этот файл.
"""

from pathlib import Path

import environ

# Корень проекта — папка, в которой лежит manage.py.
# Этот файл: config/settings/base.py, поэтому поднимаемся на три уровня вверх.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Описываем переменные окружения и их типы.
# Второй элемент кортежа — значение по умолчанию, если переменной нет.
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, []),
    # Пустая строка означает «Redis нет» — проект поднимется и без него.
    REDIS_URL=(str, ""),
    # 0 — прокси перед приложением нет. Безопасное умолчание, см. NUM_PROXIES ниже.
    DJANGO_NUM_PROXIES=(int, 0),
)

# Читаем .env из корня проекта.
# В продакшене файла может не быть — тогда переменные придут из окружения сервера.
environ.Env.read_env(BASE_DIR / ".env")

# Секретный ключ обязателен и никогда не хранится в коде.
# Если переменной нет — проект упадёт сразу, а не втихую с небезопасным ключом.
SECRET_KEY = env("DJANGO_SECRET_KEY")

DEBUG = env("DJANGO_DEBUG")

ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")


# Приложения разделены на три группы: так сразу видно, что наше, а что чужое.
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Карта сайта для поисковиков. Работает без django.contrib.sites:
    # домен берётся из самого запроса.
    "django.contrib.sitemaps",
]

THIRD_PARTY_APPS = [
    "channels",
    "corsheaders",
    "csp",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "axes",
]

LOCAL_APPS = [
    # core идёт первым: его абстрактные модели используют остальные.
    "apps.core",
    "apps.users",
    "apps.catalog",
    "apps.library",
    "apps.reviews",
    "apps.streaming",
    "apps.billing",
    # api последним: он представляет модели всех остальных приложений.
    "apps.api",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # LocaleMiddleware определяет язык из cookie, сессии или заголовка Accept-Language.
    # Должен стоять после SessionMiddleware (чтобы читать язык из сессии)
    # и до CommonMiddleware (чтобы редиректы учитывали язык).
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "axes.middleware.AxesMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Общие шаблоны (base.html, 404.html) лежат в корневой папке templates.
        # Шаблоны приложений Django найдёт сам благодаря APP_DIRS.
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# Настройки базы читаем одной строкой из DATABASE_URL.
# Формат: postgres://пользователь:пароль@хост:порт/имя_базы
DATABASES = {
    "default": env.db("DATABASE_URL"),
}

# Connection pooling: reuse connections for 5 minutes.
# Production overrides to 10 minutes.
DATABASES["default"]["CONN_MAX_AGE"] = 300
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True


# Кэш. Если REDIS_URL не задан, работаем на памяти процесса:
# проект должен подниматься на машине без Redis, просто без общего кэша
# между процессами. Код, который зовёт cache.get/set, об этом не знает.
REDIS_URL = env("REDIS_URL")

# Django Channels: WebSocket для real-time уведомлений.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}

if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "moviehub-local",
        }
    }

# Сколько живут закэшированные подборки главной страницы.
CACHE_TTL_HOME = 60 * 5

# Провайдеры видео задаются только конфигурацией окружения/инфраструктуры. В БД
# хранится ключ ресурса, а не URL, поэтому редактор не может добавить произвольный
# источник в плеер. Для локальных файлов URL строится защищённым Django-маршрутом.
STREAMING_PROVIDER_CONFIG = {
    "cloudflare_stream": {"delivery_base_url": env("CLOUDFLARE_STREAM_DELIVERY_BASE_URL", default="")},
    "cloudflare_r2": {"delivery_base_url": env("CLOUDFLARE_R2_DELIVERY_BASE_URL", default="")},
    "aws_s3": {"delivery_base_url": env("AWS_S3_DELIVERY_BASE_URL", default="")},
    "backblaze_b2": {"delivery_base_url": env("BACKBLAZE_B2_DELIVERY_BASE_URL", default="")},
    "minio": {"delivery_base_url": env("MINIO_DELIVERY_BASE_URL", default="")},
}


# Celery. Брокер — тот же Redis. Без него задачи выполнятся прямо
# в процессе запроса (task_always_eager), и разработка не встанет.
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ALWAYS_EAGER = not REDIS_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "Asia/Bishkek"

# Задачи по расписанию. Пересчёт рейтингов раз в час: считать среднюю
# оценку на каждый показ страницы дорого, когда отзывов десятки тысяч.
CELERY_BEAT_SCHEDULE = {
    "refresh-title-ratings": {
        "task": "apps.catalog.tasks.refresh_title_ratings",
        "schedule": 60 * 60,
    },
    "publish-scheduled": {
        "task": "apps.catalog.tasks.publish_scheduled_titles",
        "schedule": 60 * 5,  # Каждые 5 минут
    },
}


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# REST API.
NUM_PROXIES = env("DJANGO_NUM_PROXIES")

# CORS: разрешаем запросы к API с других доменов.
# В продакшене CORS_ALLOWED_ORIGINS берётся из переменных окружения.
CORS_URLS_REGEX = r"^/api/.*$"
CORS_ALLOW_ALL_ORIGINS = DEBUG  # Только в dev; в проде — список доменов.

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# django-axes: блокировка после 5 неудачных попыток входа за 5 минут.
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 5  # минут
AXES_RESET_ON_SUCCESS = True

# Платежи: Stripe
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")

REST_FRAMEWORK = {
    # По умолчанию читать может любой. Каждая вьюха, которая меняет данные,
    # объявляет своё правило явно — так нельзя случайно открыть запись всем.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # Сессии: тот же вход, что и на сайте. Токены добавим,
        # когда появится мобильный клиент.
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 24,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    # Ограничение частоты запросов — раздел 7 ТЗ.
    # Без него один скрипт выкачает весь каталог за минуту.
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/minute",
        "user": "300/minute",
    },
    # Сколько доверенных прокси стоит перед приложением.
    # Задать обязательно: при значении по умолчанию (None) DRF берёт ключ
    # лимита прямо из заголовка X-Forwarded-For, а его шлёт сам клиент.
    # Меняя заголовок на каждый запрос, любой обходит лимит целиком.
    # 0 — прокси нет, ключом служит REMOTE_ADDR, заголовок игнорируется.
    # За Nginx поставить 1 через DJANGO_NUM_PROXIES, иначе все посетители
    # склеятся в один ключ по адресу самого Nginx.
    "NUM_PROXIES": NUM_PROXIES,
    # Схему OpenAPI строит drf-spectacular, разбирая сериализаторы и вьюсеты.
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}


# Документация API. Описание собирается из кода, а не пишется руками,
# поэтому не может разойтись с реальным поведением эндпоинтов.
SPECTACULAR_SETTINGS = {
    "TITLE": "MovieHub API",
    "VERSION": "1.0.0",
    "DESCRIPTION": (
        "REST API каталога фильмов и сериалов MovieHub.\n\n"
        "**Чтение доступно без авторизации.** Отзывы и избранное требуют входа: "
        "используется та же сессия, что и на сайте — войдите на `/login/`, "
        "и запросы из браузера начнут проходить.\n\n"
        "**Черновики недоступны.** Записи со статусом «Черновик» не отдаются "
        "ни в списках, ни по прямой ссылке, ни через отзывы — только `404`.\n\n"
        "**Ограничение частоты:** 60 запросов в минуту для гостя, "
        "300 для авторизованного. При превышении — `429`."
    ),
    # Схема отдаётся отдельным эндпоинтом, дублировать её внутри UI незачем.
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    # Убирает /api/v1/ из имён операций: путь и так виден в адресе.
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "TAGS": [
        {"name": "titles", "description": "Фильмы и сериалы: список, карточка, похожее, избранное"},
        {"name": "reviews", "description": "Отзывы с оценкой по десятибалльной шкале"},
        {"name": "collections", "description": "Тематические подборки"},
        {"name": "genres", "description": "Справочник жанров"},
        {"name": "countries", "description": "Справочник стран"},
    ],
    "SWAGGER_UI_SETTINGS": {
        "deepLinking": True,
        "persistAuthorization": True,
        "displayRequestDuration": True,
    },
}


# Своя модель пользователя. Задана до первой миграции — поменять её
# на работающем проекте стоит очень дорого.
AUTH_USER_MODEL = "users.User"

# Куда отправлять неавторизованного и куда возвращать после входа.
LOGIN_URL = "users:login"
LOGIN_REDIRECT_URL = "catalog:home"
LOGOUT_REDIRECT_URL = "catalog:home"

# Cookie и Session настройки.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7  # 7 дней
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_SAVE_EVERY_REQUEST = False
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_USE_SESSIONS = False

LANGUAGE_COOKIE_HTTPONLY = False
LANGUAGE_COOKIE_SAMESITE = "Lax"


LANGUAGE_CODE = "ru"

# Поддерживаемые языки. Порядок в списке — порядок в переключателе.
LANGUAGES = [
    ("ru", "Русский"),
    ("en", "English"),
]

# Пути к файлам переводов.
LOCALE_PATHS = [BASE_DIR / "locale"]

# Sentry: трекинг ошибок в продакшене.
# Без переменной окружения SENTRY_DSN Sentry не активируется.
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )

TIME_ZONE = "Asia/Bishkek"
USE_I18N = True

# Храним время в базе в UTC, а показываем в TIME_ZONE.
# Это избавляет от ошибок при смене часового пояса сервера.
USE_TZ = True


# Статика: наши исходники лежат в static/,
# а collectstatic соберёт всё в staticfiles/ для продакшена.
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Медиа — файлы, которые загружают пользователи и редакторы (постеры фильмов).
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Content Security Policy: ограничивает источники контента.
# Защита от XSS: браузер не загрузит скрипты с чужих доменов.
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ("'self'",),
        "script-src": ("'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net"),
        "style-src": ("'self'", "'unsafe-inline'"),
        "img-src": ("'self'", "data:", "https:"),
        "font-src": ("'self'",),
        "connect-src": ("'self'",),
        "frame-src": (
            "'self'",
            "https://www.youtube.com",
            "https://player.vimeo.com",
            "https://rutube.ru",
        ),
        "frame-ancestors": ("'none'",),
    },
}


# Логирование — раздел 7 ТЗ.
# Пишем в консоль: контейнер и systemd сами собирают stdout, и складывать
# логи в файл внутри контейнера значит однажды их потерять.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps.streaming": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "apps.billing": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
