from django.db import models
from django.db.models import F


def story_card_prefetches(prefix=""):
    """
    Связи, без которых шаблон includes/story_card.html идёт в базу сам.

    Карточка показывает жанры, страны, студии, режиссёра и актёров. Пока
    список нужных связей был вписан только в TitleQuerySet.with_related(),
    любая вьюха, строившая запрос не от Title, про него не знала. Так и
    вышло на странице персоны: она отбирала Participation и прегружала
    только жанры, а карточка добирала персон по одному — восемь лишних
    запросов на четыре карточки, и кэш это не лечил.

    Принимает: prefix — путь до Title из текущей модели. Пусто для самого
    Title, "title__" — когда запрос строится от Participation.
    Возвращает: список аргументов для prefetch_related.
    """
    from django.db.models import Prefetch

    from apps.catalog.models.person import Participation

    return [
        f"{prefix}genres",
        f"{prefix}countries",
        f"{prefix}studios",
        Prefetch(
            f"{prefix}participations",
            # select_related("person") обязателен: без него Django достанет
            # участия без самих персон и сходит в базу за каждым именем.
            queryset=Participation.objects.select_related("person"),
        ),
    ]


class TitleQuerySet(models.QuerySet):
    """
    Готовые запросы к каталогу.

    Держим их здесь, а не переписываем в каждой вьюхе: фильтр
    «только опубликованное» понадобится и на главной, и в каталоге,
    и в поиске. Забыть его хотя бы в одном месте — значит показать
    посетителям черновики.

    Обращаемся к статусу через self.model, а не импортируем Title:
    иначе managers.py и models/title.py импортировали бы друг друга.
    """

    def published(self):
        # Получаем только то, что редактор опубликовал
        return self.filter(status=self.model.Status.PUBLISHED)

    def movies(self):
        return self.filter(type=self.model.Type.MOVIE)

    def series(self):
        return self.filter(type=self.model.Type.SERIES)

    def with_related(self):
        """
        Подтягивает всё, что нужно карточке каталога, одним набором запросов.

        Без этого список из 24 карточек делает десятки лишних обращений
        к базе — по одному на жанры, страны и каждое имя из съёмочной группы.
        Состав связей описан в story_card_prefetches: он общий с вьюхами,
        которые строят запрос не от Title.
        """
        return self.prefetch_related(*story_card_prefetches())

    @staticmethod
    def _crew_prefetch():
        """Prefetch участий с персонами — общий для with_related и with_crew."""
        return story_card_prefetches()[-1]

    def with_crew(self):
        """
        Подтягивает съёмочную группу для страницы фильма.

        Prefetch с явным queryset обязателен: без него Django достанет
        участия без самих персон и на каждое имя сходит в базу отдельно.
        """
        # with_related уже тянет участия; prefetch того же атрибута вторым
        # queryset'ом Django считает ошибкой. В _prefetch_related_lookups
        # лежат объекты Prefetch (lookup в атрибуте prefetch_to), а не строки.
        already = [
            p for p in self._prefetch_related_lookups
            if getattr(p, "prefetch_to", p) == "participations"
        ]
        if already:
            return self
        return self.prefetch_related(self._crew_prefetch())

    def in_collection(self, collection):
        """
        Содержимое подборки в порядке, который задал редактор.

        Принимает: экземпляр Collection.
        Возвращает: QuerySet записей этой подборки.

        Явный order_by обязателен: Meta.ordering у CollectionItem
        не распространяется на Title через обратную связь. Правило живёт
        здесь, а не во вьюхах, — его спрашивают и сайт, и API.
        """
        # «pk» вторым ключом — тайбрейкер: order у CollectionItem неуникален
        # (по умолчанию 100), и записи с одинаковым order могли бы меняться
        # местами между страницами подборки, дублируясь и пропадая.
        return self.filter(collection_items__collection=collection).order_by(
            "collection_items__order", "pk"
        )

    def rated(self):
        """Только то, что уже кто-то оценил."""
        return self.filter(rating_count__gt=0)

    def top_rated(self):
        """
        Лучшее по оценкам.

        Читаем готовое поле rating_average — ни JOIN, ни GROUP BY.
        Поле обновляют apps.catalog.services.update_title_rating
        и часовая задача Celery.
        """
        return self.rated().order_by(F("rating_average").desc(nulls_last=True), "-rating_count")
