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
    path("actors/", views.ActorListView.as_view(), name="actor_list"),
    path("directors/", views.DirectorListView.as_view(), name="director_list"),

    path("studios/", views.StudioListView.as_view(), name="studio_list"),
    path("studios/<slug:slug>/", views.StudioDetailView.as_view(), name="studio_detail"),
    path("awards/", views.AwardListView.as_view(), name="award_list"),
    path("awards/<slug:slug>/", views.AwardDetailView.as_view(), name="award_detail"),

    path("search-by-actor/", views.ActorSearchView.as_view(), name="actor_search"),
    path("random/", views.RandomTitleView.as_view(), name="random_title"),

    path("collections/", views.CollectionListView.as_view(), name="collection_list"),
    path("collections/<slug:slug>/", views.CollectionDetailView.as_view(), name="collection_detail"),
]
