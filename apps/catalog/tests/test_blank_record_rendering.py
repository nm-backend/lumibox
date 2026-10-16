"""Пустые поля записи не должны печататься как «None» и как «0».

Так выглядит часть каталога. Год в базе обязателен (NOT NULL), поэтому
«года нет» — это запись с нулём: файловый импорт сохраняет ровно так
(`import_titles`), а импорт из Vibix такие записи просто пропускает.
Остальные поля пустые по-настоящему: дата премьеры, длительность,
рейтинги — у них NULL разрешён.

Проверяем на настоящих страницах: страница фильма, каталог и главная.
Так следующий незащищённый вывод поля находится сразу, а не глазами
при чтении шаблонов.
"""

from django.test import TestCase

from apps.catalog.models import Title
from apps.core.test_factories import create_title


class BlankRecordTests(TestCase):
    def setUp(self):
        self.title = create_title(
            name="Запись без подробностей",
            slug="zapis-bez-podrobnostey",
            type=Title.Type.MOVIE,
        )
        Title.objects.filter(pk=self.title.pk).update(
            # Год обязателен в схеме: «нет года» в базе — это ноль.
            release_year=0,
            release_date=None,
            original_name="",
            duration_minutes=None,
            imdb_rating=None,
            kp_rating=None,
            rating_average=None,
            age_rating="",
            quality="",
            description="",
            short_description="",
            voice_acting="",
            trailer_url="",
            latest_episode_info="",
        )
        self.title.refresh_from_db()
        self.url = f"/title/{self.title.slug}/"

    def page(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.content.decode("utf-8", "ignore")

    def test_no_page_prints_none(self):
        for name, url in (
            ("страница фильма", self.url),
            ("каталог", "/catalog/"),
            ("главная", "/"),
        ):
            with self.subTest(page=name):
                self.assertNotIn("None", self.page(url), f"{name} печатает None")

    def test_year_zero_is_not_shown_as_a_year(self):
        html = self.page(self.url)
        self.assertNotIn("(0)", html, "заголовок вкладки или предпросмотр показал год 0")
        self.assertNotIn("0 года", html, "описание показало год 0")
        # Пустая строка выпуска не должна уходить поисковику как дата.
        self.assertNotIn('"datePublished"', html)

    def test_blank_record_is_actually_on_the_page(self):
        """Канарейка: если записи на странице нет, обе проверки выше бессмысленны."""
        self.assertIn("Запись без подробностей", self.page(self.url))

    def test_template_leftovers_never_reach_the_page(self):
        """Следы шаблонного комментария не должны попадать в разметку.

        `{# #}` разбирается только в одну строку. Многострочный такой
        комментарий Django считает текстом страницы и печатает его —
        а видно это лишь на записи, у которой есть те поля, о которых
        комментарий написан. Поэтому проверяем на заполненной записи тоже.
        """
        full = create_title(name="Заполненная запись", slug="zapolnennaya", release_year=2010)
        Title.objects.filter(pk=full.pk).update(duration_minutes=120, kp_rating="7.5")
        for name, url in (("пустая", self.url), ("заполненная", f"/title/{full.slug}/")):
            with self.subTest(record=name):
                html = self.page(url)
                self.assertNotIn("{#", html)
                self.assertNotIn("{%", html)
