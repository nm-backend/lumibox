from apps.library.models import Favorite, WatchHistory


def toggle_favorite(user, title):
    """
    Добавляет запись в избранное или убирает её оттуда.

    Принимает: авторизованного пользователя и запись каталога.
    Возвращает: True — теперь в избранном, False — убрали.

    get_or_create, а не filter().first() с последующим create(): между
    проверкой и записью успевает вклиниться второй запрос, оба видят
    «записи нет», и второй падает на ограничении уникальности.
    Двойного клика по кнопке достаточно, чтобы получить 500.
    get_or_create ловит эту ошибку внутри себя и перечитывает запись.
    """
    favorite, created = Favorite.objects.get_or_create(user=user, title=title)

    if created:
        return True

    favorite.delete()
    return False


def remember_view(user, title):
    """
    Отмечает, что пользователь открыл страницу записи.

    update_or_create вместо create: в истории нужна одна запись на фильм
    с обновлённым временем, а не сотня одинаковых строк.
    Поле watched_at обновится само — у него auto_now.
    """
    if not user.is_authenticated:
        return

    WatchHistory.objects.update_or_create(user=user, title=title)
