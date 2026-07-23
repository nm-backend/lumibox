from django.db import models


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
        Подтягивает жанры и страны заранее, одним запросом на всё.

        Без этого список из 24 карточек делает 48 лишних запросов
        к базе — по одному на жанры и страны каждой карточки.
        """
        return self.prefetch_related("genres", "countries", "studios")

    def with_crew(self):
        """
        Подтягивает съёмочную группу для страницы фильма.

        Prefetch с явным queryset обязателен: без него Django достанет
        участия без самих персон и на каждое имя сходит в базу отдельно.
        """
        from django.db.models import Prefetch

        from apps.catalog.models.person import Participation

        return self.prefetch_related(
            Prefetch(
                "participations",
                queryset=Participation.objects.select_related("person"),
            )
        )

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
        return self.rated().order_by("-rating_average", "-rating_count")
