from django.urls import path

from apps.catalog import views

# Пространство имён: в шаблонах ссылки пишутся как {% url 'catalog:title_list' %}.
app_name = "catalog"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("catalog/", views.TitleListView.as_view(), name="title_list"),
    path("title/<slug:slug>/", views.TitleDetailView.as_view(), name="title_detail"),

    path("genres/", views.GenreListView.as_view(), name="genre_list"),
    path("genres/<slug:slug>/", views.GenreTitleListView.as_view(), name="genre_titles"),

    path("countries/", views.CountryListView.as_view(), name="country_list"),
    path("countries/<slug:slug>/", views.CountryTitleListView.as_view(), name="country_titles"),

    path("persons/<slug:slug>/", views.PersonDetailView.as_view(), name="person_detail"),

    path("collections/", views.CollectionListView.as_view(), name="collection_list"),
    path("collections/<slug:slug>/", views.CollectionDetailView.as_view(), name="collection_detail"),
]
