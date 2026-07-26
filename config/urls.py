"""
Главный список маршрутов MovieHub.

Здесь только подключение приложений. Сами маршруты живут
в urls.py каждого приложения — так корневой файл не разрастётся.

i18n_patterns добавляет префикс языка (/ru/, /en/) к пользовательским
страницам. API, admin, healthz и статика остаются без префикса:
они либо не зависят от языка, либо используют свой механизм.
"""

from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path, re_path

from apps.catalog.sitemaps import sitemaps
from apps.core.admin_dashboard import admin_dashboard, admin_dashboard_api
from apps.core.views import health_check, robots_txt, serve_public_media

# Error handlers
handler404 = "apps.core.views.custom_404"
handler500 = "apps.core.views.custom_500"

# Маршруты без языкового префикса: API, админка, health check, статика.
urlpatterns = [
    path("healthz/", health_check, name="health"),
    path("admin/dashboard/", admin_dashboard, name="admin_dashboard"),
    path("admin/dashboard/api/", admin_dashboard_api, name="admin_dashboard_api"),
    path("admin/", admin.site.urls),
    path("api/", include("apps.api.urls")),
    # set_language принимает POST с выбором языка и перенаправляет обратно.
    path("i18n/", include("django.conf.urls.i18n")),
    # SEO: карта сайта и robots.txt — без префикса, чтобы адрес был стабильным.
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path("robots.txt", robots_txt, name="robots_txt"),
]

# Пользовательские страницы с языковым префиксом: /ru/catalog/, /en/title/...
# prefix_default_language=False: русский тоже получает префикс.
# Это делает URL-структуру консистентной и понятной поисковикам.
urlpatterns += i18n_patterns(
    path("", include("apps.users.urls")),
    path("", include("apps.library.urls")),
    path("", include("apps.reviews.urls")),
    path("", include("apps.streaming.urls")),
    path("", include("apps.catalog.urls")),
    prefix_default_language=False,
)

# Отдача загруженных файлов (постеры, кадры).
urlpatterns += [
    re_path(
        r"^media/(?P<path>.*)$",
        serve_public_media,
        {"document_root": settings.MEDIA_ROOT},
    ),
]
