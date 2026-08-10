"""
Тесты обсуждений.

Комментарий — не отзыв: отзыв это оценка, одна на пользователя, а здесь
разговор, где отвечают друг другу. Вложенность ровно одна, и почти все
проверки ниже стерегут именно её и модерацию.
"""

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.catalog.models import Title
from apps.core.test_factories import create_title, create_user
from apps.reviews.admin import CommentAdmin
from apps.reviews.models import Comment
from apps.reviews.services import save_comment


def make_comment(title, user=None, text="Текст", **kwargs):
    return Comment.objects.create(
        user=user or create_user(), title=title, text=text, **kwargs
    )


class CommentModelTests(TestCase):
    def test_reply_to_reply_rejected_by_clean(self):
        """Глубина ленты ровно два уровня."""
        title = create_title()
        root = make_comment(title, text="Корень")
        reply = make_comment(title, text="Ответ", parent=root)

        with self.assertRaises(ValidationError):
            Comment(user=create_user(), title=title, text="Глубже", parent=reply).full_clean()

    def test_published_excludes_hidden(self):
        title = create_title()
        make_comment(title, text="Виден")
        make_comment(title, text="Скрыт", status=Comment.Status.HIDDEN)

        self.assertEqual(Comment.objects.published().count(), 1)

    def test_roots_excludes_replies(self):
        title = create_title()
        root = make_comment(title, text="Корень")
        make_comment(title, text="Ответ", parent=root)

        self.assertEqual(list(Comment.objects.roots()), [root])


class SaveCommentServiceTests(TestCase):
    """
    Сервис бережёт текст зрителя: ответ на ответ не отклоняется, а
    прикрепляется к той же ветке. Человек нажал «Ответить» под чужим
    ответом — терять его текст из-за правила о глубине нельзя.
    """

    def test_reply_to_reply_collapses_to_root(self):
        title = create_title()
        root = make_comment(title, text="Корень")
        reply = make_comment(title, text="Ответ", parent=root)

        created = save_comment(create_user(), title, "Ещё глубже", parent=reply)

        self.assertEqual(created.parent, root)

    def test_parent_from_another_title_dropped(self):
        """Ответ не должен уехать в ленту чужого фильма."""
        foreign_root = make_comment(create_title(), text="Чужой")
        title = create_title()

        created = save_comment(create_user(), title, "Мой", parent=foreign_root)

        self.assertIsNone(created.parent)
        self.assertEqual(created.title, title)


class CommentViewTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.title = create_title(name="Фильм с обсуждением")
        self.add_url = reverse("reviews:comment_add", args=[self.title.slug])

    def test_guest_cannot_comment(self):
        response = self.client.post(self.add_url, {"text": "Привет"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Comment.objects.count(), 0)

    def test_user_can_comment(self):
        self.client.force_login(self.user)

        self.client.post(self.add_url, {"text": "Отличное кино"})

        comment = Comment.objects.get()
        self.assertEqual(comment.user, self.user)
        self.assertEqual(comment.title, self.title)
        self.assertIsNone(comment.parent)

    def test_empty_comment_rejected(self):
        self.client.force_login(self.user)

        self.client.post(self.add_url, {"text": "   "})

        self.assertEqual(Comment.objects.count(), 0)

    def test_user_can_reply(self):
        root = make_comment(self.title, text="Корень")
        self.client.force_login(self.user)

        self.client.post(self.add_url, {"text": "Согласен", "parent": root.pk})

        self.assertEqual(Comment.objects.get(parent=root).user, self.user)

    def test_cannot_comment_draft(self):
        draft = create_title(status=Title.Status.DRAFT)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("reviews:comment_add", args=[draft.slug]), {"text": "Привет"}
        )

        self.assertEqual(response.status_code, 404)

    def test_user_deletes_own_comment(self):
        comment = make_comment(self.title, user=self.user, text="Моё")
        self.client.force_login(self.user)

        self.client.post(reverse("reviews:comment_delete", args=[comment.pk]))

        self.assertEqual(Comment.objects.count(), 0)

    def test_user_cannot_delete_foreign_comment(self):
        comment = make_comment(self.title, text="Чужое")
        self.client.force_login(self.user)

        response = self.client.post(reverse("reviews:comment_delete", args=[comment.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Comment.objects.count(), 1)

    def test_deleting_root_removes_replies(self):
        root = make_comment(self.title, user=self.user, text="Корень")
        make_comment(self.title, text="Ответ", parent=root)
        self.client.force_login(self.user)

        self.client.post(reverse("reviews:comment_delete", args=[root.pk]))

        self.assertEqual(Comment.objects.count(), 0)


class CommentFeedTests(TestCase):
    def setUp(self):
        self.title = create_title(name="Фильм с лентой")

    def test_feed_shows_comments_and_replies(self):
        root = make_comment(self.title, text="Корневой текст")
        make_comment(self.title, text="Ответный текст", parent=root)

        response = self.client.get(self.title.get_absolute_url())

        self.assertContains(response, "Корневой текст")
        self.assertContains(response, "Ответный текст")
        self.assertEqual(response.context["comments_count"], 2)

    def test_hidden_comment_not_shown(self):
        make_comment(self.title, text="Скрытый текст", status=Comment.Status.HIDDEN)

        response = self.client.get(self.title.get_absolute_url())

        self.assertNotContains(response, "Скрытый текст")
        self.assertEqual(response.context["comments_count"], 0)

    def test_hidden_reply_not_shown(self):
        root = make_comment(self.title, text="Корневой текст")
        make_comment(self.title, text="Скрытый ответ", parent=root, status=Comment.Status.HIDDEN)

        response = self.client.get(self.title.get_absolute_url())

        self.assertNotContains(response, "Скрытый ответ")
        self.assertEqual(response.context["comments_count"], 1)

    def test_feed_does_not_grow_queries_with_rows(self):
        """Ответы приходят префетчем — число запросов не зависит от длины ленты."""
        self._fill(3)
        # Прогрев: первый заход наполняет кэш сайдбара и справочников,
        # и без него мы сравнивали бы холодный запрос с горячим, а не
        # короткую ленту с длинной.
        self.client.get(self.title.get_absolute_url())

        with CaptureQueriesContext(connection) as few:
            self.client.get(self.title.get_absolute_url())

        self._fill(6)
        with CaptureQueriesContext(connection) as many:
            self.client.get(self.title.get_absolute_url())

        self.assertEqual(len(few), len(many))

    def _fill(self, count):
        for _ in range(count):
            root = make_comment(self.title, text="Корень")
            make_comment(self.title, text="Ответ", parent=root)


class CommentModerationTests(TestCase):
    """Скрытый корень уносит ответы: ответ без вопроса читается как обрывок."""

    def test_hiding_root_hides_replies(self):
        title = create_title()
        root = make_comment(title, text="Корень")
        reply = make_comment(title, text="Ответ", parent=root)

        request = RequestFactory().get("/")
        request.user = create_user(is_staff=True, is_superuser=True)
        request.session = "session"
        request._messages = FallbackStorage(request)

        CommentAdmin(Comment, AdminSite()).hide(request, Comment.objects.filter(pk=root.pk))

        root.refresh_from_db()
        reply.refresh_from_db()
        self.assertEqual(root.status, Comment.Status.HIDDEN)
        self.assertEqual(reply.status, Comment.Status.HIDDEN)


class CommentApiTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.title = create_title(name="Фильм для API")
        self.url = reverse("api:v1:title-comments", args=[self.title.slug])

    def test_list_returns_roots_with_replies(self):
        root = make_comment(self.title, text="Корень API")
        make_comment(self.title, text="Ответ API", parent=root)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["text"], "Корень API")
        self.assertEqual(results[0]["replies"][0]["text"], "Ответ API")

    def test_hidden_not_exposed(self):
        make_comment(self.title, text="Скрыт API", status=Comment.Status.HIDDEN)

        response = self.client.get(self.url)

        self.assertEqual(response.json()["results"], [])

    def test_guest_cannot_create(self):
        response = self.client.post(self.url, {"text": "Гость"})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Comment.objects.count(), 0)

    def test_user_creates_comment(self):
        self.client.force_login(self.user)

        response = self.client.post(self.url, {"text": "Через API"})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Comment.objects.get().user, self.user)

    def test_comments_of_draft_title_not_exposed(self):
        draft = create_title(status=Title.Status.DRAFT)
        make_comment(draft, text="Черновой")

        response = self.client.get(reverse("api:v1:title-comments", args=[draft.slug]))

        self.assertEqual(response.status_code, 404)

    def test_author_deletes_own(self):
        comment = make_comment(self.title, user=self.user, text="Моё API")
        self.client.force_login(self.user)

        response = self.client.delete(
            reverse("api:v1:title-comment-detail", args=[self.title.slug, comment.pk])
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(Comment.objects.count(), 0)

    def test_stranger_cannot_delete(self):
        comment = make_comment(self.title, text="Чужое API")
        self.client.force_login(self.user)

        response = self.client.delete(
            reverse("api:v1:title-comment-detail", args=[self.title.slug, comment.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Comment.objects.count(), 1)
