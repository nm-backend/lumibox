"""
Разметка, от которой зависит мобильный вид.

Сами размеры и брейкпоинты живут в CSS, и Django-тест их не проверит.
Зато он стережёт то, на чём мобильные правки держатся: какие ссылки лежат
в выдвижном меню, свёрнута ли панель фильтров, есть ли якорь у плеера.
Каждая из этих мелочей уже ломалась, и каждая стоила зрителю с телефона
экрана прокрутки или целого раздела.
"""

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.catalog.models import Title
from apps.catalog.tests.test_episodes import create_source
from apps.core.test_factories import create_genre, create_title


class MobileDrawerLinksTests(TestCase):
    """Выдвижное меню — единственная навигация на телефоне и планшете."""

    def setUp(self):
        self.response = self.client.get(reverse("catalog:home"))
        self.html = self.response.content.decode()

    def test_shows_showcase_pages_not_sort_shortcuts(self):
        """
        «Новинки» вели из меню на каталог с сортировкой по дате, а из строки
        разделов — на страницу /new/. Один ярлык на два адреса, и сами витрины
        с телефона были недостижимы.
        """
        drawer = self._drawer()

        self.assertIn(reverse("catalog:new"), drawer)
        self.assertIn(reverse("catalog:premieres"), drawer)
        self.assertIn(reverse("catalog:top"), drawer)

    def test_covers_every_supported_type_without_extra_links(self):
        """
        На ≤900px строка разделов скрыта, и её пункты обязаны быть здесь:
        иначе тип фильма перестаёт существовать для телефона.
        """
        drawer = self._drawer()
        supported_types = [value for value, _label in Title.Type.choices]

        for value in supported_types:
            with self.subTest(type=value):
                self.assertIn(f"?type={value}", drawer)
        self.assertEqual(drawer.count("?type="), len(supported_types))

    def _drawer(self):
        """Кусок разметки с выдвижным меню — по нему и сверяем ссылки."""
        start = self.html.index('id="mobile-nav"')
        end = self.html.index("</nav>", start)
        return self.html[start:end]


class CatalogFiltersCollapsedTests(TestCase):
    """
    Панель фильтров стояла раскрытой всегда: на телефоне двенадцать полей
    отодвигали первую карточку фильма на 1809-й пиксель.
    """

    def setUp(self):
        self.url = reverse("catalog:title_list")
        create_title(name="Какой-нибудь фильм", genres=[create_genre()])

    def test_panel_is_collapsed_by_default(self):
        response = self.client.get(self.url)

        self.assertContains(response, '<details class="filters">')

    def test_panel_stays_collapsed_when_filter_applied(self):
        response = self.client.get(self.url, {"type": "series"})

        self.assertContains(response, '<details class="filters">')

    def test_applied_filters_are_visible_outside_the_panel(self):
        """
        Свернуть панель можно только потому, что отбор виден и без неё.
        Если плашки уедут обратно внутрь <details>, зритель перестанет
        понимать, почему в каталоге три фильма вместо пятнадцати.
        """
        html = self.client.get(self.url, {"type": "series"}).content.decode()

        chips = html.index('class="filters__active"')
        panel = html.index('<details class="filters">')
        self.assertLess(chips, panel)


class PlayerAnchorTests(TestCase):
    """Кнопка «Смотреть онлайн» в шапке карточки ведёт к плееру якорем."""

    def test_anchor_and_button_exist_together(self):
        title = create_title(name="Фильм с плеером")
        create_source(title=title)

        response = self.client.get(title.get_absolute_url())

        self.assertContains(response, 'id="player"')
        self.assertContains(response, 'href="#player"')

    def test_no_dead_anchor_without_playback(self):
        """Без источников секции плеера нет — значит, и ссылки на неё быть не должно."""
        title = create_title(name="Фильм без источников")

        response = self.client.get(title.get_absolute_url())

        self.assertNotContains(response, 'href="#player"')


class CookieConsentMarkupTests(TestCase):
    """Кнопка баннера должна быть настоящей .button, а не мёртвым .btn."""

    def test_accept_uses_project_button_classes(self):
        html = self.client.get(reverse("catalog:home")).content.decode()

        self.assertIn("cookie-consent__accept", html)
        self.assertIn("button button--primary", html)
        self.assertNotIn("btn btn--primary", html)


class HomeMarkupTests(TestCase):
    """Лишний </div> на главной закрывал .container из base.html."""

    def test_seo_block_stays_inside_home_wrap(self):
        html = self.client.get(reverse("catalog:home")).content.decode()
        start = html.index('<div class="lb-home">')
        depth = 0
        end = None
        i = start
        while i < len(html):
            if html.startswith("<div", i):
                depth += 1
                i += 4
                continue
            if html.startswith("</div>", i):
                depth -= 1
                i += 6
                if depth == 0:
                    end = i
                    break
                continue
            i += 1

        self.assertIsNotNone(end)
        home = html[start:end]
        self.assertIn('class="lb-seo"', home)
        self.assertLess(home.index("lb-contentwrap"), home.index("lb-seo"))


class AdsNetworkMarkupTests(TestCase):
    """Реклама появляется на странице только по флагу."""

    def setUp(self):
        self.url = reverse("catalog:home")

    def test_no_ads_without_flag(self):
        """Флаг выключен — ни тега, ни скрипта, ни слотов рекламы."""
        response = self.client.get(self.url)
        self.assertNotContains(response, 'id="vibix_union"')
        self.assertNotContains(response, "v-js-menu.run")
        self.assertNotContains(response, 'data-pm-b=')

    @override_settings(
        ADS_NETWORK_ENABLED=True,
        ADS_NETWORK_PUBLISHER_ID="678503345",
        ADS_NETWORK_ADD_TYPES="sticker,pcsticker,banners",
    )
    def test_ads_with_flag(self):
        """Флаг включён — тег с ID издателя и форматами, лоадер, слот баннера."""
        response = self.client.get(self.url)
        self.assertContains(response, 'id="vibix_union"')
        self.assertContains(response, 'data-publisher_id="678503345"')
        self.assertContains(response, 'data-add_types="sticker,pcsticker,banners"')
        self.assertContains(response, "https://v-js-menu.run/public/lib.en.min.js")
        self.assertContains(response, 'data-pm-b="728x90"')
