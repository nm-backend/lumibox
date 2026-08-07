from django.db import models


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

    def with_title(self, user=None):
        """
        Подтягивает запись каталога и её жанры заранее.

        Принимает: user — для бейджа «Продолжить с S1E3» на карточке
        (последняя просмотренная серия пользователя).
        Возвращает: QuerySet, готовый к отрисовке карточек.

        Без этого список из 24 карточек лезет в базу за каждой записью
        и за жанрами каждой из них.
        """
        from django.db.models import Prefetch

        from apps.library.models import WatchHistory

        prefetches = ["title__genres"]
        if user is not None and user.is_authenticated:
            prefetches.append(
                Prefetch(
                    "title__watchhistory_set",
                    queryset=WatchHistory.objects.filter(
                        user=user, episode__isnull=False
                    ).select_related("episode"),
                    to_attr="progress_item",
                )
            )
        return self.select_related("title").prefetch_related(*prefetches)
