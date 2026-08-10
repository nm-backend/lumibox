from django.db import models
from django.db.models import F


def story_card_prefetches(prefix="", user=None):
    """
    Связи, без которых шаблон includes/story_card.html идёт в базу сам.

    Карточка показывает жанры и (для вошедших) бейдж продолжения просмотра.
    Пока список нужных связей был вписан только в TitleQuerySet.with_related(),
    любая вьюха, строившая запрос не от Title, про него не знала. Так и
    вышло на странице персоны: она отбирала Participation и прегружала
    только жанры, а карточка добирала персон по одному — восемь лишних
    запросов на четыре карточки, и кэш это не лечил.

    Принимает: prefix — путь до Title из текущей модели. Пусто для самого
    Title, "title__" — когда запрос строится от Participation.
    user — для префетча прогресса просмотра (бейдж «Смотреть с S1E3»).
    Возвращает: список аргументов для prefetch_related.
    """
    from django.db.models import Prefetch

    # Страны нужны карточке каталога: кинго-карточка показывает строку
    # «Год / Страна / Жанр», и без prefetch каждая страна шла бы в базу
    # отдельным запросом на каждую карточку.
    prefetches = [f"{prefix}genres", f"{prefix}countries"]
    if user is not None and user.is_authenticated:
        from apps.library.models import WatchHistory

        prefetches.append(
            Prefetch(
                f"{prefix}watchhistory_set",
                queryset=WatchHistory.objects.filter(
                    user=user, episode__isnull=False
                ).select_related("episode"),
                to_attr="progress_item",
            )
        )
    return prefetches


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

    def cartoons(self):
        return self.filter(type=self.model.Type.CARTOON)

    def tv_shows(self):
        return self.filter(type=self.model.Type.TV_SHOW)

    def most_viewed(self, limit=None):
        """Самые просматриваемые: порядок по счётчику просмотров."""
        qs = self.order_by(F("views_count").desc(nulls_last=True), F("published_at").desc(nulls_last=True))
        if limit is not None:
            qs = qs[:limit]
        return qs

    def with_related(self):
        """
        Подтягивает всё, что нужно карточке каталога, одним набором запросов.

        Без этого список из 24 карточек делает десятки лишних обращений
        к базе — по одному на жанры и каждое имя из съёмочной группы.
        Состав связей описан в story_card_prefetches: он общий с вьюхами,
        которые строят запрос не от Title. Страны и студии карточке не
        нужны — их подтягивает with_detail только на странице записи.
        """
        return self.prefetch_related(*story_card_prefetches())

    @staticmethod
    def _crew_prefetch():
        """Prefetch участий с персонами — общий для with_related и with_crew."""
        from django.db.models import Prefetch

        from apps.catalog.models.person import Participation

        return Prefetch(
            "participations",
            # select_related("person") обязателен: без него Django достанет
            # участия без самих персон и сходит в базу за каждым именем.
            queryset=Participation.objects.select_related("person"),
        )

    def with_detail(self):
        """
        Полный набор для страницы записи и API-карточки: страны и студии
        добавляются только здесь, спискам карточек они не нужны.
        """
        return self.with_related().with_crew().prefetch_related("countries", "studios")

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

    def with_frames(self):
        """
        Подтягивает кадры галереи для страницы фильма.

        Шаблон страницы фильма проверяет title.frames.all дважды — для
        вкладки «Галерея» и в самом контенте. Без prefetch каждый вызов
        шёл в базу отдельным запросом. Сортировка берётся из Meta.ordering
        модели (порядок задаёт редактор), как и в других prefetch.
        """
        return self.prefetch_related("frames")

    def with_sources(self):
        """
        Подтягивает источники видео вместе с озвучкой.

        select_related("voice") обязателен: иначе выбор озвучки в плеере
        сходил бы в базу за каждым названием отдельно. Спискам каталога
        источники не нужны — только странице записи.
        """
        from django.db.models import Prefetch

        from apps.catalog.models.playback import PlaybackSource

        return self.prefetch_related(
            Prefetch(
                "playback_sources",
                queryset=PlaybackSource.objects.select_related("voice"),
            )
        )

    def with_episodes(self):
        """
        Подтягивает серии для страницы фильма.

        Список серий строится один раз (для плеера и для метаданных
        «N сезонов · M серий»), поэтому выносим его в prefetch, а не
        тянем из get_context_data. В списках каталога не используется:
        story_card_prefetches его не содержит, чтобы не платить
        лишним запросом за каждую страницу каталога.
        """
        return self.prefetch_related("episodes")

    def with_progress(self, user):
        """
        Подтягивает последнюю просмотренную серию для каждого тайтла.

        Нужен карточке каталога: бейдж «Продолжить с S1E3» строится из
        записи истории просмотра, и без prefetch каждый тайтл сходил бы
        в базу отдельно. Гостям ничего не предзагружаем — у них истории
        нет. Точечный queryset с select_related: в бейдже нужна сама серия,
        а не её связь с записью.
        """
        if not user.is_authenticated:
            return self
        from django.db.models import Prefetch

        from apps.library.models import WatchHistory

        return self.prefetch_related(
            Prefetch(
                "watchhistory_set",
                queryset=WatchHistory.objects.filter(
                    user=user, episode__isnull=False
                ).select_related("episode"),
                to_attr="progress_item",
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
        return self.rated().order_by(F("rating_average").desc(nulls_last=True), "-rating_count")
