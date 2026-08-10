from apps.library.models import Favorite, WatchHistory, Watchlist


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


def toggle_watchlist(user, title):
    """
    Добавляет запись в «Смотреть позже» или убирает её оттуда.

    Устроено так же, как toggle_favorite: get_or_create защищает
    от двойного клика на ограничении уникальности.
    """
    watchlist_item, created = Watchlist.objects.get_or_create(user=user, title=title)

    if created:
        return True

    watchlist_item.delete()
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


def remember_progress(user, title, episode=None, position=0, duration=None):
    """
    Запоминает, где именно остановился зритель.

    Принимает: пользователя, запись, необязательную серию, позицию в секундах
    и полную длительность (её сообщает плеер, из модели её не взять —
    duration_minutes у серии заполняет редактор и часто не заполняет).

    Та же строка, что и в истории просмотров: один фильм — одна запись,
    и позиция живёт в ней же. Отдельная таблица прогресса дала бы историю
    «серия за серией», но за неё пришлось бы платить на каждом кадре
    таймкода, а показываем мы всё равно только последнее место.

    Отрицательную позицию и мусор от клиента приводим к нулю: значение
    приходит из браузера, то есть ему нельзя верить.
    """
    if not user.is_authenticated:
        return None

    defaults = {"position_seconds": max(0, int(position or 0))}
    # Серию перезаписываем только когда её прислали: обычный просмотр
    # страницы не должен стирать «остановился на третьей».
    if episode is not None:
        defaults["episode"] = episode
    if duration:
        defaults["duration_seconds"] = max(0, int(duration))

    history, _ = WatchHistory.objects.update_or_create(
        user=user, title=title, defaults=defaults
    )
    return history


def remember_episode_start(user, title, episode):
    """
    Отмечает начало просмотра серии — позиция сбрасывается в ноль.

    Тонкая обёртка над remember_progress: её зовут плеер и API, когда
    зритель переключил серию, а не продолжил ту же.
    """
    return remember_progress(user, title, episode=episode, position=0)
