from django.contrib import admin

# Подписи админки. Django сам импортирует admin.py каждого приложения,
# поэтому достаточно задать их один раз здесь.
admin.site.site_header = "LumiBox"
admin.site.site_title = "LumiBox"
admin.site.index_title = "Управление каталогом"
