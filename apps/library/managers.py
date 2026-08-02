from django.db import models
from django.db.models import Prefetch

from apps.catalog.models.person import Participation


class UserTitleRelationQuerySet(models.QuerySet):
    """
    Готовые запросы к связям «пользователь — запись каталога».

    Общий менеджер для Favorite и WatchHistory: у них одинаковая форма
    и одинаковые требования к запросам. Правило «карточке нужны сама
    запись и её жанры» описано здесь один раз — иначе его пришлось бы
    помнить в каждой вьюхе, а забывчивость стоит N+1.
    """

    def for_user(self, user):
        """
        Принимает: пользователя.
        Возвращает: QuerySet только его записей.
        """
        return self.filter(user=user)

    def with_title(self):
        """
        Подтягивает запись каталога и её жанры заранее.

        Возвращает: QuerySet, готовый к отрисовке карточек.

        Без этого список из 24 карточек лезет в базу за каждой записью
        и за жанрами каждой из них.
        """
        return self.select_related("title").prefetch_related(
            "title__genres",
            "title__countries",
            "title__studios",
            Prefetch(
                "title__participations",
                queryset=Participation.objects.select_related("person"),
            ),
        )
