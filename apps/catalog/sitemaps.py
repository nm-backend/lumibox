from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from apps.catalog.models import Award, Collection, Country, Genre, Person, Studio, Title


class TitleSitemap(Sitemap):
    """Карта сайта для фильмов и сериалов."""

    changefreq = "weekly"
    priority = 0.8

    def items(self):
        # Только опубликованное: черновики отдают 404,
        # и роботу такие ссылки предлагать нельзя.
        return Title.objects.published()

    def lastmod(self, title):
        return title.updated_at


class ReferenceSitemap(Sitemap):
    """Общая основа для карт жанров и стран."""

    changefreq = "monthly"
    priority = 0.5

    model = None
    url_name = ""

    def items(self):
        return self.model.objects.all()

    def location(self, reference):
        return reverse(self.url_name, args=[reference.slug])


class GenreSitemap(ReferenceSitemap):
    model = Genre
    url_name = "catalog:genre_titles"


class CountrySitemap(ReferenceSitemap):
    model = Country
    url_name = "catalog:country_titles"


class StudioSitemap(ReferenceSitemap):
    model = Studio
    url_name = "catalog:studio_detail"


class AwardSitemap(ReferenceSitemap):
    model = Award
    url_name = "catalog:award_detail"


class PersonSitemap(Sitemap):
    """Персоны: актёры, режиссёры и прочая съёмочная группа."""

    changefreq = "weekly"
    priority = 0.6

    def items(self):
        return Person.objects.all()

    def lastmod(self, person):
        return person.updated_at


class CollectionSitemap(Sitemap):
    """Тематические подборки."""

    changefreq = "weekly"
    priority = 0.6

    def items(self):
        # Только опубликованные: черновик подборки отдаёт 404.
        return Collection.objects.published()

    def lastmod(self, collection):
        return collection.updated_at


class StaticSitemap(Sitemap):
    """Постоянные страницы: главная, каталог, списки жанров и стран."""

    changefreq = "daily"
    priority = 1.0

    def items(self):
        return [
            "catalog:home",
            "catalog:title_list",
            "catalog:genre_list",
            "catalog:country_list",
            "catalog:actor_list",
            "catalog:director_list",
            "catalog:studio_list",
            "catalog:award_list",
        ]

    def location(self, url_name):
        return reverse(url_name)


# Словарь для подключения в config/urls.py
sitemaps = {
    "static": StaticSitemap,
    "titles": TitleSitemap,
    "genres": GenreSitemap,
    "countries": CountrySitemap,
    "studios": StudioSitemap,
    "awards": AwardSitemap,
    "persons": PersonSitemap,
    "collections": CollectionSitemap,
}
