from django.core.cache import cache
from django.test import TestCase

from apps.catalog.models import Title
from apps.catalog.services import (
    get_crew_by_role,
    get_home_sections,
    get_recommendations,
    get_similar_titles,
)
from apps.catalog.tasks import refresh_title_ratings
from apps.core.test_factories import (
    create_genre,
    create_participation,
    create_person,
    create_review,
    create_title,
    create_user,
)
from apps.library.models import Favorite
from apps.library.services import remember_view, toggle_favorite
from apps.reviews.models import Review


class RatingTests(TestCase):
    """
    Рейтинг денормализован в поля модели. Эти тесты сторожат главное:
    поля должны обновляться при любом изменении отзыва.
    """

    def setUp(self):
        self.title = create_title()

    def test_rating_updated_on_review_create(self):
        create_review(title=self.title, rating=8)
        self.title.refresh_from_db()

        self.assertEqual(float(self.title.rating_average), 8.0)
        self.assertEqual(self.title.rating_count, 1)

    def test_rating_is_average_of_reviews(self):
        create_review(title=self.title, rating=10)
        create_review(title=self.title, rating=6)
        self.title.refresh_from_db()

        self.assertEqual(float(self.title.rating_average), 8.0)
        self.assertEqual(self.title.rating_count, 2)

    def test_rating_updated_on_review_delete(self):
        review = create_review(title=self.title, rating=10)
        create_review(title=self.title, rating=6)

        review.delete()
        self.title.refresh_from_db()

        self.assertEqual(float(self.title.rating_average), 6.0)
        self.assertEqual(self.title.rating_count, 1)

    def test_hidden_reviews_do_not_affect_rating(self):
        """Скрытый модерацией отзыв не должен влиять на оценку."""
        create_review(title=self.title, rating=10)
        create_review(title=self.title, rating=2, status=Review.Status.HIDDEN)
        self.title.refresh_from_db()

        self.assertEqual(float(self.title.rating_average), 10.0)
        self.assertEqual(self.title.rating_count, 1)

    def test_rating_reset_when_last_review_gone(self):
        review = create_review(title=self.title, rating=7)
        review.delete()
        self.title.refresh_from_db()

        self.assertIsNone(self.title.rating_average)
        self.assertEqual(self.title.rating_count, 0)

    def test_refresh_task_repairs_broken_values(self):
        """
        Задача-страховка чинит расхождения после массовых операций.
        Ломаем поле напрямую через update — сигналы так не срабатывают.
        """
        create_review(title=self.title, rating=9)
        Title.objects.filter(pk=self.title.pk).update(rating_average=1, rating_count=99)

        refresh_title_ratings()
        self.title.refresh_from_db()

        self.assertEqual(float(self.title.rating_average), 9.0)
        self.assertEqual(self.title.rating_count, 1)


class SimilarTitlesTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()
    def test_more_shared_genres_ranks_higher(self):
        drama = create_genre()
        thriller = create_genre()

        source = create_title(genres=[drama, thriller])
        two_matches = create_title(genres=[drama, thriller])
        one_match = create_title(genres=[drama])
        no_match = create_title(genres=[create_genre()])

        similar = list(get_similar_titles(source))

        self.assertEqual(similar[0], two_matches)
        self.assertIn(one_match, similar)
        self.assertNotIn(no_match, similar)

    def test_source_excluded_from_its_own_similar(self):
        genre = create_genre()
        source = create_title(genres=[genre])
        create_title(genres=[genre])

        self.assertNotIn(source, get_similar_titles(source))

    def test_drafts_never_appear(self):
        genre = create_genre()
        source = create_title(genres=[genre])
        draft = create_title(genres=[genre], status=Title.Status.DRAFT)

        self.assertNotIn(draft, get_similar_titles(source))

    def test_title_without_genres_returns_empty(self):
        self.assertEqual(list(get_similar_titles(create_title())), [])

    def test_manual_choice_wins_over_genre_heuristic(self):
        """
        Выбор редактора важнее автоподбора: он знает о связях,
        которых в жанрах не видно (продолжение, тот же режиссёр).
        """
        genre = create_genre()
        source = create_title(genres=[genre])
        by_genre = create_title(genres=[genre])
        hand_picked = create_title(name="Выбран вручную")

        source.related_titles.set([hand_picked])

        similar = list(get_similar_titles(source))
        self.assertEqual(similar, [hand_picked])
        self.assertNotIn(by_genre, similar)

    def test_manual_draft_is_not_shown(self):
        """Даже выбранный вручную черновик наружу не попадёт."""
        source = create_title()
        draft = create_title(status=Title.Status.DRAFT)
        source.related_titles.set([draft])

        self.assertEqual(list(get_similar_titles(source)), [])


class RecommendationTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()
    def test_based_on_favorite_genres(self):
        user = create_user()
        liked_genre = create_genre()
        other_genre = create_genre()

        favorite = create_title(genres=[liked_genre])
        Favorite.objects.create(user=user, title=favorite)

        matching = create_title(genres=[liked_genre])
        unrelated = create_title(genres=[other_genre])

        recommendations = list(get_recommendations(user))

        self.assertIn(matching, recommendations)
        self.assertNotIn(unrelated, recommendations)

    def test_already_favorited_not_recommended(self):
        user = create_user()
        genre = create_genre()
        favorite = create_title(genres=[genre])
        Favorite.objects.create(user=user, title=favorite)
        create_title(genres=[genre])

        self.assertNotIn(favorite, get_recommendations(user))

    def test_watched_not_recommended(self):
        user = create_user()
        genre = create_genre()
        Favorite.objects.create(user=user, title=create_title(genres=[genre]))

        watched = create_title(genres=[genre])
        remember_view(user, watched)

        self.assertNotIn(watched, get_recommendations(user))

    def test_user_without_favorites_gets_fresh_titles(self):
        """Пустой блок рекомендаций выглядел бы сломанным."""
        user = create_user()
        create_title()

        self.assertEqual(len(get_recommendations(user)), 1)


class CrewTests(TestCase):
    def test_grouped_by_role_director_first(self):
        from apps.catalog.models import Participation

        title = create_title()
        create_participation(title=title, role=Participation.Role.ACTOR)
        create_participation(title=title, role=Participation.Role.DIRECTOR)

        crew = get_crew_by_role(title)
        roles = [role_label for role_label, _ in crew]

        self.assertEqual(roles, ["Режиссёр", "Актёр"])

    def test_empty_crew(self):
        self.assertEqual(get_crew_by_role(create_title()), [])

    def test_kg_crew_filter_names_and_limit(self):
        from django.template import Context, Template

        from apps.catalog.models import Participation
        from apps.catalog.templatetags.catalog_filters import kg_crew

        title = create_title()
        director = create_person(name="Кристофер Нолан")
        for i in range(6):
            create_participation(
                title=title, person=create_person(name=f"Актёр {i}"), role=Participation.Role.ACTOR
            )
        create_participation(title=title, person=director, role=Participation.Role.DIRECTOR)

        self.assertEqual(kg_crew(title, "director"), "Кристофер Нолан")
        self.assertEqual(len(kg_crew(title, "actor").split(" / ")), 5)
        self.assertEqual(kg_crew(title, "writer"), "")

        rendered = Template("{% load catalog_filters %}{{ t|kg_crew:'actor' }}").render(
            Context({"t": title})
        )
        self.assertTrue(rendered.startswith("Актёр 0 / "))


class HomeCacheTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_sections_cached(self):
        create_title()
        first = get_home_sections()

        # Вторым вызовом запросов в базу быть не должно — всё из кэша.
        with self.assertNumQueries(0):
            second = get_home_sections()

        self.assertEqual(len(first["new_titles"]), len(second["new_titles"]))

    def test_cache_dropped_when_title_published(self):
        """Новый фильм должен появиться на главной сразу, а не через 5 минут."""
        create_title(name="Первый")
        get_home_sections()

        create_title(name="Второй")
        sections = get_home_sections()

        self.assertEqual(len(sections["new_titles"]), 2)

    def test_sections_hold_lists_not_lazy_querysets(self):
        """В кэш должен попасть результат, а не ленивый QuerySet."""
        create_title()
        sections = get_home_sections()
        self.assertIsInstance(sections["new_titles"], list)


class CollectionOrderingTests(TestCase):
    """
    Сторож против тихой поломки: annotate() строит GROUP BY, а для таких
    запросов Django сбрасывает Meta.ordering. Порядок тогда назначает СУБД —
    подборки перемешиваются, а при пагинации ещё и дублируются.
    Ошибку не видно ни в одном 200-ответе, поэтому проверяем явно.
    """

    def setUp(self):
        cache.clear()
        self.titled = create_title()

    def tearDown(self):
        cache.clear()

    def make_collection(self, name, order):
        from apps.catalog.models import Collection, CollectionItem

        collection = Collection.objects.create(
            name=name,
            slug=name.lower(),
            order=order,
            is_published=True,
            is_featured=True,
        )
        # Пустые подборки сервис отбрасывает — кладём внутрь хотя бы одну запись.
        CollectionItem.objects.create(collection=collection, title=self.titled, order=1)
        return collection

    def test_featured_collections_follow_editor_order(self):
        from apps.catalog.services import get_featured_collections

        last = self.make_collection("Third", order=30)
        first = self.make_collection("First", order=10)
        middle = self.make_collection("Second", order=20)

        self.assertEqual(list(get_featured_collections()), [first, middle, last])

    def test_collection_list_page_is_ordered(self):
        from django.urls import reverse

        self.make_collection("Third", order=30)
        self.make_collection("First", order=10)

        response = self.client.get(reverse("catalog:collection_list"))
        collections = list(response.context["collections"])

        self.assertTrue(
            response.context["collections"].ordered,
            "QuerySet без сортировки — пагинация начнёт терять и дублировать записи",
        )
        self.assertEqual([c.name for c in collections], ["First", "Third"])


class ReferenceOrderingTests(TestCase):
    """Та же ловушка annotate + GROUP BY, но на списке жанров."""

    def test_genre_list_is_alphabetical(self):
        from django.urls import reverse

        from apps.catalog.models import Genre

        # Создаём заведомо не по алфавиту: при сломанной сортировке
        # база вернёт их в порядке вставки, и тест это поймает.
        # Slug латиницей — в маршруте стоит [-a-zA-Z0-9_], кириллица туда не попадёт.
        for name, slug in [("Ужасы", "ord-horror"), ("Драма", "ord-drama"), ("Комедия", "ord-comedy")]:
            genre = Genre.objects.create(name=name, slug=slug)
            create_title(genres=[genre])

        response = self.client.get(reverse("catalog:genre_list"))
        names = [reference.name for reference in response.context["references"]]

        self.assertEqual(names, sorted(names), "жанры выводятся не по алфавиту")


class FavoriteServiceTests(TestCase):
    def test_toggle_adds_then_removes(self):
        user = create_user()
        title = create_title()

        self.assertTrue(toggle_favorite(user, title))
        self.assertEqual(Favorite.objects.filter(user=user, title=title).count(), 1)

        self.assertFalse(toggle_favorite(user, title))
        self.assertEqual(Favorite.objects.filter(user=user, title=title).count(), 0)


class WatchHistoryServiceTests(TestCase):
    def test_repeat_views_keep_single_row(self):
        from apps.library.models import WatchHistory

        user = create_user()
        title = create_title()

        remember_view(user, title)
        remember_view(user, title)
        remember_view(user, title)

        self.assertEqual(WatchHistory.objects.filter(user=user, title=title).count(), 1)

    def test_anonymous_view_not_recorded(self):
        from django.contrib.auth.models import AnonymousUser

        from apps.library.models import WatchHistory

        remember_view(AnonymousUser(), create_title())
        self.assertEqual(WatchHistory.objects.count(), 0)
