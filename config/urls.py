"""
Главный список маршрутов MovieHub.

Здесь только подключение приложений. Сами маршруты живут
в urls.py каждого приложения — так корневой файл не разрастётся.
"""

from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path, re_path
from django.views.generic import TemplateView
from django.views.static import serve

from apps.catalog.sitemaps import sitemaps
from apps.core.views import health_check

urlpatterns = [
    # Проба живости для хостинга и мониторинга. Первой в списке и без
    # завершающего редиректа: платформа должна получать ответ мгновенно.
    path("healthz/", health_check, name="health"),

    path("admin/", admin.site.urls),

    path("api/", include("apps.api.urls")),

    # SEO: карта сайта и инструкции для поисковых роботов.
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="django.contrib.sitemaps.views.sitemap"),
    path("robots.txt", TemplateView.as_view(template_name="robots.txt", content_type="text/plain")),
    path("", include("apps.users.urls")),
    path("", include("apps.library.urls")),
    path("", include("apps.reviews.urls")),
    # Каталог подключаем последним: у него маршрут "" для главной,
    # и он не должен перехватывать адреса остальных приложений.
    path("", include("apps.catalog.urls")),
]

# Отдача загруженных файлов (постеры, кадры). Работает и при DEBUG=False:
# на PaaS вроде Render перед Django нет Nginx, а WhiteNoise отдаёт только
# статику, не медиа, — без этого маршрута картинки отдавали бы 404.
# serve() из django.views.static защищён от обхода каталога. Django-раздача
# медиа не для больших нагрузок: когда файлов станет много, их выносят
# в объектное хранилище (S3/R2) через django-storages, и маршрут убирают.
urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
