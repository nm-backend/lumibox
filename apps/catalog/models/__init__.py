"""
Модели каталога.

Файл собирает модели из отдельных модулей в один пакет, чтобы
в остальном коде писать привычное `from apps.catalog.models import Title`,
не зная, в каком файле модель лежит физически.
"""

from apps.catalog.models.collection import Collection, CollectionItem
from apps.catalog.models.episode import Episode
from apps.catalog.models.frame import Frame
from apps.catalog.models.industry import Award, Franchise, Studio, TitleAward
from apps.catalog.models.person import Participation, Person
from apps.catalog.models.playback import PlaybackSource
from apps.catalog.models.reference import Country, Genre, VoiceOver
from apps.catalog.models.title import Title
from apps.catalog.models.video_service import VideoServiceSyncState

__all__ = [
    "Collection",
    "CollectionItem",
    "Country",
    "Episode",
    "Frame",
    "Franchise",
    "Genre",
    "Award",
    "Participation",
    "Person",
    "PlaybackSource",
    "Studio",
    "Title",
    "TitleAward",
    "VideoServiceSyncState",
    "VoiceOver",
]
