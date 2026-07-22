"""
Гонки: два одновременных запроса на одно действие.

Эти тесты используют TransactionTestCase, а не TestCase: обычный TestCase
заворачивает тест в одну транзакцию, поэтому другой поток просто не увидит
записанное — гонку в нём воспроизвести нельзя.

Каждый поток закрывает свои соединения: Django не делится соединением
между потоками, и без close_all() тест оставит их висеть.
"""

import threading

from django.db import connections
from django.test import TransactionTestCase

from apps.core.test_factories import create_title, create_user
from apps.library.models import Favorite
from apps.library.services import toggle_favorite
from apps.reviews.models import Review
from apps.reviews.services import save_review


def run_concurrently(action, threads=2):
    """
    Запускает action одновременно в нескольких потоках.

    Принимает: функцию без аргументов и число потоков.
    Возвращает: список имён исключений, которые упали в потоках.

    Barrier нужен, чтобы потоки стартовали строго вместе: без него
    первый успевает закончить раньше, чем второй начнёт, и гонки не будет.
    """
    barrier = threading.Barrier(threads)
    errors = []

    def worker():
        try:
            barrier.wait()
            action()
        except Exception as error:
            errors.append(type(error).__name__)
        finally:
            connections.close_all()

    pool = [threading.Thread(target=worker) for _ in range(threads)]
    for thread in pool:
        thread.start()
    for thread in pool:
        thread.join()

    return errors


class FavoriteRaceTests(TransactionTestCase):
    def test_double_click_does_not_crash(self):
        """
        Кнопку избранного кликают мышью, и двойной клик — обычное дело.
        Раньше filter().first() + create() ловил на этом IntegrityError и 500.
        """
        user = create_user()
        title = create_title()

        errors = run_concurrently(lambda: toggle_favorite(user, title))

        self.assertEqual(errors, [], "одновременные клики уронили сервер")
        # Переключатель: один поток добавил, второй убрал. Дублей быть не может.
        self.assertLessEqual(Favorite.objects.filter(user=user, title=title).count(), 1)


class ReviewRaceTests(TransactionTestCase):
    def test_double_submit_does_not_crash(self):
        """
        Двойная отправка формы отзыва раньше давала 500 на ограничении
        unique_review_per_user.
        """
        user = create_user()
        title = create_title()

        errors = run_concurrently(lambda: save_review(user=user, title=title, rating=8, text="x"))

        self.assertEqual(errors, [], "одновременные отправки уронили сервер")
        self.assertEqual(Review.objects.filter(user=user, title=title).count(), 1)
