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

# Платформы сообщают выданный домен собственной переменной, и у каждой она
# своя. Подхватываем обе, чтобы сайт открылся сразу после деплоя — ещё до
# того как владелец подключит свой домен. Раньше учитывался только Render,
# и на Railway первый же запрос упал бы с DisallowedHost.
PLATFORM_HOSTS = [
    env("RENDER_EXTERNAL_HOSTNAME", default=""),  # noqa: F405
    env("RAILWAY_PUBLIC_DOMAIN", default=""),  # noqa: F405
]
ALLOWED_HOSTS = [*ALLOWED_HOSTS, *[host for host in PLATFORM_HOSTS if host]]

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

# Статика по-прежнему отдаётся через whitenoise из контейнера.
# Не кладём её в R2 — так быстрее: не нужен лишний HTTP к R2 на каждый CSS.
_STATICFILES_STORAGE = {
    "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
}

if _USE_R2:
    _R2_OPTIONS = {
        "access_key": env("AWS_ACCESS_KEY_ID"),
        "secret_key": env("AWS_SECRET_ACCESS_KEY"),
        "bucket_name": env("AWS_STORAGE_BUCKET_NAME"),
        "region_name": env("AWS_S3_REGION_NAME", default="auto"),
        "endpoint_url": env("AWS_S3_ENDPOINT_URL"),
        "signature_version": "s3v4",
        # Не перезаписывать файлы — каждый новый файл получает уникальное имя.
        "file_overwrite": False,
        # Имена файлов уникальны (file_overwrite=False), поэтому кэш на сутки
        # безопасен: обновление файла всегда новый URL. Уменьшает трафик
        # из бакета и готовит раздачу к выносу за CDN.
        "object_parameters": {"CacheControl": "public, max-age=86400"},
    }

    STORAGES = {
        "default": {
            # Cloudflare R2 — S3-совместимое объектное хранилище.
            # Файлы не теряются при перезапуске, в отличие от локального диска.
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                **_R2_OPTIONS,
                # Публичный URL (R2.dev, свой домен, CDN перед бакетом).
                # Если не задан, Django строит адрес из endpoint_url и имени бакета.
                "custom_domain": env("CLOUDFLARE_R2_PUBLIC_URL", default="") or None,
                # Каталог открытый: смотреть можно без регистрации и подписки,
                # поэтому и постеры, и видео раздаются публичным адресом.
                "default_acl": "public-read",
                # Ссылки НЕ подписываем — и это осознанно.
                #
                # По умолчанию django-storages подписывает адреса, когда
                # custom_domain не задан, и не подписывает, когда задан. То есть
                # одна незаполненная переменная меняла поведение раздачи:
                # с подписью адрес живёт час, и зритель, вернувшийся к паузе
                # позже, получал отказ при перемотке — Range-запрос уходил
                # с протухшей подписью. Хуже того, подпись здесь ничего не
                # охраняет: объект и так public-read, его открывает любой,
                # кто знает адрес.
                #
                # Если каталог когда-нибудь станет платным, приватность делается
                # не здесь: нужно снять public-read, включить querystring_auth
                # и отдавать ссылку через вьюху, которая проверяет права
                # (заготовка для этого — префикс private_media/ в
                # apps/core/media_serving.py, он уже закрыт от прямой раздачи).
                "querystring_auth": False,
            },
        },
        "staticfiles": _STATICFILES_STORAGE,
    }
else:
    # R2 не настроен — локальный диск.
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": _STATICFILES_STORAGE,
    }


# Весь трафик переводим на HTTPS.
SECURE_SSL_REDIRECT = True

# Почта. В base.py по умолчанию console-бэкенд: письма печатаются в лог
# воркера, но не уходят. Как только задан EMAIL_HOST (SMTP Mailgun/SendGrid/
# Gmail), включаем настоящую отправку — без неё сброс пароля не работает.
if env("EMAIL_HOST", default=""):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

# Nginx принимает HTTPS и ходит в Django по HTTP.
# Этот заголовок объясняет Django, что исходный запрос всё-таки был защищённым.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# За прокси nginx реальный IP лежит в X-Forwarded-For. Без этого axes
# (брутфорс-защита /login/) и лимит регистраций видели бы только адрес
# nginx — один на всех посетителей, и блокировка одного сработала бы
# для всех.
AXES_BEHIND_REVERSE_PROXY = True
# ВАЖНО: AXES_PROXY_COUNT убран — в axes 8.x он объявлен устаревшим
# (W004) и падает check --deploy. Число прокси зашито в сам
# AXES_BEHIND_REVERSE_PROXY (см. документацию axes).

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
# ─── Sentry: отслеживание ошибок ─────────────────────────────────
# Бесплатный tier (5 000 событий/мес). Если SENTRY_DSN не задан,
# инициализация пропускается — проект работает без Sentry.
_SENTRY_DSN = env("SENTRY_DSN", default="")  # noqa: F405
if _SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    from apps.core.middleware import get_request_id

    def _tag_request_id(event, hint):
        # Привязываем событие к запросу: по request_id его находят
        # в логах приложения и наоборот.
        event.setdefault("tags", {})["request_id"] = get_request_id()
        return event

    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        integrations=[DjangoIntegration()],
        # Отправляем не больше одного события в секунду — защита от
        # лавины ошибок при падении внешнего сервиса.
        traces_sample_rate=0.1,
        send_default_pii=False,
        environment="production",
        before_send=_tag_request_id,
    )
