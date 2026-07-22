from django.contrib import admin

# Подписи админки. Django сам импортирует admin.py каждого приложения,
# поэтому достаточно задать их один раз здесь.
admin.site.site_header = "MovieHub"
admin.site.site_title = "MovieHub"
admin.site.index_title = "Управление каталогом"
