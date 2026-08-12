"""
Базовые настройки LumiBox.

Здесь лежит только то, что одинаково для всех окружений.
Всё, что различается (отладка, домены, безопасность), находится
в development.py и production.py — они импортируют этот файл.
"""

from pathlib import Path
from typing import Any

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

# Email — настройки SMTP. По умолчанию письма печатаются в консоль.
# В продакшене задайте EMAIL_HOST/EMAIL_HOST_USER/EMAIL_HOST_PASSWORD
# через переменные окружения (Mailgun, SendGrid, Gmail SMTP — все
# бесплатны на малых объёмах).
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="LumiBox <noreply@lumibox.app>")
SERVER_EMAIL = env("SERVER_EMAIL", default="root@lumibox.app")

# Таймаут SMTP-соединения, секунды. preflight на старте контейнера открывает
# живое соединение с почтовым сервером: без таймаута недоступный хост
# держал бы boot (а значит, и порт) до упора. smtplib сам берёт значение
# по умолчанию, если переменная не задана.
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)

# Google Analytics / Google Tag Manager — идентификатор отслеживания.
# Если не задан, трекинг не вставляется в шаблон.
GA_MEASUREMENT_ID = env("GA_MEASUREMENT_ID", default="")

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
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    # Блокировка аккаунта после неудачных попыток входа.
    "axes",
]

LOCAL_APPS = [
    # core идёт первым: его абстрактные модели используют остальные.
    "apps.core",
    "apps.users",
    "apps.catalog",
    "apps.library",
    "apps.reviews",
    # api последним: он представляет модели всех остальных приложений.
    "apps.api",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # ID запроса: X-Request-ID в ответе и request_id в логах и Sentry.
    "apps.core.middleware.RequestIdMiddleware",
    # Сжатие ответов gzip — уменьшает размер HTML/JSON/CSS/JS.
    "django.middleware.gzip.GZipMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # Локализация: определяет язык по сессии, cookie или Accept-Language.
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Защита от brute-force: считает неудачные попытки и блокирует.
    "axes.middleware.AxesMiddleware",
    # Content-Security-Policy: defence-in-depth заголовок, ограничивает,
    # какие ресурсы браузер может загружать на странице.
    "apps.core.middleware.ContentSecurityPolicyMiddleware",
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
                # Google Analytics ID — доступен во всех шаблонах как
                # {{ ga_measurement_id }}. Если не задан — пустая строка,
                # в base.html блок gtag не рендерится.
                "apps.core.context_processors.global_settings",
                "apps.core.context_processors.static_version",
                "apps.core.context_processors.lb_topnav",
"apps.core.context_processors.lb_sidebar",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Настройки базы читаем одной строкой из DATABASE_URL.
# Формат: postgres://пользователь:пароль@хост:порт/имя_базы
DATABASES = {
    "default": env.db("DATABASE_URL"),
}

# Переиспользование соединений. По умолчанию Django открывает новое
# соединение на каждый запрос и закрывает его в конце: для PostgreSQL это
# полный TCP-рукопожатие плюс аутентификация — заметная доля времени
# лёгкой страницы. Держим соединение открытым между запросами.
#
# 60 секунд, а не «навсегда»: у управляемых баз (Render, Railway) есть
# свой предел живых соединений, и вечные соединения от нескольких воркеров
# упираются в него быстрее, чем кажется. Значение переопределяется
# переменной, если тариф базы позволяет больше.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DJANGO_CONN_MAX_AGE", default=60)

# Проверять живость соединения перед выдачей из пула. Без этого первый
# запрос после того, как база разорвала соединение по своему таймауту,
# падал бы с InterfaceError вместо переподключения.
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

# Таймаут установки TCP-соединения, секунды. Без него «мёртвая» база
# (истёкший бесплатный Postgres Render, недоступный хост) держит подключение
# на уровне libpq минутами: migrate на старте контейнера зависает, gunicorn
# не занимает порт, и платформа убивает выкладку по таймауту сканирования
# порта. С таймаутом старт падает за секунды с понятной ошибкой подключения.
# Только для Postgres: sqlite-бэкенд локальной разработки не знает этого
# параметра и упал бы с TypeError.
if DATABASES["default"]["ENGINE"].endswith("postgresql"):
    DATABASES["default"]["OPTIONS"] = {
        "connect_timeout": env.int("DJANGO_DB_CONNECT_TIMEOUT", default=5),
    }


# Кэш. Если REDIS_URL не задан, работаем на памяти процесса:
# проект должен подниматься на машине без Redis, просто без общего кэша
# между процессами. Код, который зовёт cache.get/set, об этом не знает.
REDIS_URL = env("REDIS_URL")

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
            "LOCATION": "lumibox-local",
        }
    }

# Сколько живут закэшированные подборки главной страницы — для
# 100K пользователей нужно реже ходить в базу, но при этом редактор
# должен видеть свои правки в reasonable время.
CACHE_TTL_HOME = 60 * 5  # 5 минут — баланс: прогретый кэш, редактор видит правки
CACHE_TTL_HOME_LONG = 60 * 10  # 10 минут для медленно меняющихся блоков
# Справочники (жанры, страны) меняются редко — кэш на час.
CACHE_TTL_REFERENCE = 60 * 60
# Похожие фильмы — меняются только при добавлении новых связей
CACHE_TTL_SIMILAR = 60 * 30
# Персональные рекомендации — индивидуальны для пользователя
CACHE_TTL_RECOMMENDATIONS = 60 * 5

# Celery. Брокер — тот же Redis. Без него задачи выполнятся прямо
# в процессе запроса (task_always_eager), и разработка не встанет.
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ALWAYS_EAGER = not REDIS_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "Asia/Bishkek"

# Задачи по расписанию для масштабирования до 100K пользователей
CELERY_BEAT_SCHEDULE = {
    # Пересчёт рейтингов раз в час: страховка после массовых правок
    "refresh-title-ratings": {
        "task": "apps.catalog.tasks.refresh_title_ratings",
        "schedule": 60 * 60,
    },
    # Прогрев кэша главной каждые 2 минуты — первый посетитель не ждёт
    "warm-home-cache": {
        "task": "apps.catalog.tasks.warm_home_cache",
        "schedule": 60 * 2,
    },
    # Прогрев справочников каждые 30 минут
    "warm-reference-caches": {
        "task": "apps.catalog.tasks.warm_reference_caches",
        "schedule": 60 * 30,
    },
}


# Пароли хешируются Argon2 — самым устойчивым к GPU-атакам алгоритмом.
# PBKDF2 и BCrypt оставлены как fallback для старых хешей при обновлении.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]

# Сколько неудачных попыток входа блокируют аккаунт (через django-axes).
# 5 попыток — стандарт OWASP. После блокировки аккаунт открывается
# через час или вручную из админки.
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # часов
AXES_RESET_ON_SUCCESS = True
# Блокируем по связке (username, IP) — чтобы разные пользователи
# с одного IP не блокировали друг друга.
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]

# Authentication backends: django-axes должен быть ПЕРВЫМ,
# чтобы он обрабатывал запрос до стандартного бэкенда.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# REST API.
NUM_PROXIES = env("DJANGO_NUM_PROXIES")

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
    "TITLE": "LumiBox API",
    "VERSION": "1.0.0",
    "DESCRIPTION": (
        "REST API каталога фильмов и сериалов LumiBox.\n\n"
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
        {"name": "comments", "description": "Обсуждение записи: комментарии и ответы"},
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


# Поддерживаемые языки: русский, английский. Кыргызский был удалён
# полностью — переводы, переключатель, каталог локали.
LANGUAGE_CODE = "ru"
LANGUAGES = [
    ("ru", "Русский"),
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]

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

# Лимиты загрузки. Изображения до 10 МБ принимаются в память;
# видео (до 4 ГБ, валидатор validate_video_size) пишутся во временный
# файл на диск и затем в MEDIA_ROOT — без этого Django держал бы их в RAM.
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# Тип объявлен явно: у боевых настроек внутри лежит ещё и вложенный OPTIONS,
# и без аннотации mypy выводит по здешнему словарю тип «строки» и считает
# production.py ошибкой.
STORAGES: dict[str, dict[str, Any]] = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Логирование — раздел 7 ТЗ.
# Пишем в консоль: контейнер и systemd сами собирают stdout, и складывать
# логи в файл внутри контейнера значит однажды их потерять.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} [rid={request_id}] {message}",
            "style": "{",
        },
    },
    "filters": {
        "request_id": {
            "()": "apps.core.middleware.RequestIdFilter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["request_id"],
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
        # События безопасности: попытки подбора пароля, CSRF-атаки,
        # доступ к несуществующим ресурсам с подозрительными адресами.
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        # Ошибки запросов — то, из-за чего посетитель видит 500.
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
    },
}


# Python 3.14 workaround: подменяет BaseContext.__copy__,
# который ломается на Python 3.14.14+.
# TODO: Убрать после обновления Django.
from apps.core import py314_compat  # noqa: F401, E402
