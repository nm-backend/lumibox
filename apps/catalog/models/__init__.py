"""
Модели каталога.

Файл собирает модели из отдельных модулей в один пакет, чтобы
в остальном коде писать привычное `from apps.catalog.models import Title`,
не зная, в каком файле модель лежит физически.
"""

from apps.catalog.models.collection import Collection, CollectionItem
from apps.catalog.models.frame import Frame
from apps.catalog.models.industry import Award, Studio, TitleAward
from apps.catalog.models.person import Participation, Person
from apps.catalog.models.reference import Country, Genre
from apps.catalog.models.title import Title

__all__ = [
    "Collection",
    "CollectionItem",
    "Country",
    "Frame",
    "Genre",
    "Award",
    "Participation",
    "Person",
    "Studio",
    "Title",
    "TitleAward",
]
