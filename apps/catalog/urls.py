from django.urls import path

from apps.catalog import views

# Пространство имён: в шаблонах ссылки пишутся как {% url 'catalog:title_list' %}.
app_name = "catalog"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("catalog/", views.TitleListView.as_view(), name="title_list"),
    path("title/<slug:slug>/", views.TitleDetailView.as_view(), name="title_detail"),

    # Разделы-витрины. Каждый — тот же каталог с суженной выборкой, поэтому
    # фильтры, сортировка и пагинация работают в них без единой лишней строки:
    # все наследуют TitleListView и трогают только get_base_queryset().
    path("new/", views.NewTitlesView.as_view(), name="new"),
    path("popular/", views.PopularTitlesView.as_view(), name="popular"),
    path("top/", views.TopRatedTitlesView.as_view(), name="top"),
    path("premieres/", views.PremieresView.as_view(), name="premieres"),
    path("year/<int:year>/", views.YearTitleListView.as_view(), name="year_titles"),

    path("genres/", views.GenreListView.as_view(), name="genre_list"),
    path("genres/<slug:slug>/", views.GenreTitleListView.as_view(), name="genre_titles"),

    path("countries/", views.CountryListView.as_view(), name="country_list"),
    path("countries/<slug:slug>/", views.CountryTitleListView.as_view(), name="country_titles"),

    path("persons/<slug:slug>/", views.PersonDetailView.as_view(), name="person_detail"),
    path("actors/", views.ActorListView.as_view(), name="actor_list"),
    path("directors/", views.DirectorListView.as_view(), name="director_list"),

    path("studios/", views.StudioListView.as_view(), name="studio_list"),
    path("studios/<slug:slug>/", views.StudioDetailView.as_view(), name="studio_detail"),
    path("franchises/", views.FranchiseListView.as_view(), name="franchise_list"),
    path("franchises/<slug:slug>/", views.FranchiseDetailView.as_view(), name="franchise_detail"),
    path("awards/", views.AwardListView.as_view(), name="award_list"),
    path("awards/<slug:slug>/", views.AwardDetailView.as_view(), name="award_detail"),

    path("search/", views.SearchView.as_view(), name="search"),
    path("search-by-actor/", views.ActorSearchView.as_view(), name="actor_search"),
    path("random/", views.RandomTitleView.as_view(), name="random_title"),

    path("collections/", views.CollectionListView.as_view(), name="collection_list"),
    path("collections/<slug:slug>/", views.CollectionDetailView.as_view(), name="collection_detail"),
]
