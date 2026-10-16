"""
Тесты WebP-копий.

Главное, что здесь стережётся, — работа на хранилище без пути на диске.
Именно так ведёт себя Cloudflare R2, и именно там конвертация раньше
пропускалась целиком: в продакшене копий не появлялось вовсе, а фильтр
молча отдавал оригиналы. Локальный диск проверяется заодно, но он и раньше
работал.
"""

import io
import os
import shutil
import tempfile

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from PIL import Image

from apps.catalog.models import Title
from apps.catalog.templatetags.catalog_filters import webp_url
from apps.catalog.webp import SIZED_VARIANTS, convert_field, webp_name
from apps.core.test_factories import (
    create_collection,
    create_participation,
    create_person,
    create_title,
    create_user,
)


def jpeg_bytes(size=(600, 900)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (30, 90, 60)).save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


class MemoryStorage(Storage):
    """
    Хранилище в памяти, у которого нет пути на диске.

    path() выбрасывает NotImplementedError — как у django-storages для S3
    и R2. Пока конвертация опиралась на field.path, на таком хранилище она
    не запускалась.
    """

    def __init__(self):
        self.files = {}

    def _open(self, name, mode="rb"):
        return ContentFile(self.files[name])

    def _save(self, name, content):
        self.files[name] = content.read()
        return name

    def exists(self, name):
        return name in self.files

    def url(self, name):
        return f"https://bucket.example/{name}"

    def path(self, name):
        raise NotImplementedError("хранилище без пути на диске")


class FakeField:
    """Минимум от ImageFieldFile, который нужен конвертации и фильтрам."""

    def __init__(self, name, storage):
        self.name = name
        self.storage = storage

    @property
    def url(self):
        """Как у ImageFieldFile: адрес файла в хранилище."""
        return self.storage.url(self.name)


class WebpConversionTests(TestCase):
    def setUp(self):
        self.storage = MemoryStorage()
        self.storage.files["posters/film.jpg"] = jpeg_bytes()
        self.field = FakeField("posters/film.jpg", self.storage)

    def test_creates_copy_on_storage_without_disk_path(self):
        result = convert_field(self.field)

        self.assertEqual(result, "posters/film.webp")
        self.assertTrue(self.storage.exists("posters/film.webp"))

    def test_copy_is_smaller_than_original(self):
        """Смысл конвертации — вес. Если копия не легче, она не нужна."""
        convert_field(self.field)

        original = len(self.storage.files["posters/film.jpg"])
        copy = len(self.storage.files["posters/film.webp"])
        self.assertLess(copy, original)

    def test_second_call_does_not_rewrite(self):
        convert_field(self.field)
        first = self.storage.files["posters/film.webp"]

        self.assertEqual(convert_field(self.field), "posters/film.webp")
        self.assertIs(self.storage.files["posters/film.webp"], first)
        self.assertEqual(len(self.storage.files), 2)

    def test_gif_is_left_alone(self):
        """Анимация в WebP теряется, а статичный кадр — уже не та картинка."""
        self.storage.files["posters/animated.gif"] = b"GIF89a-not-really"
        field = FakeField("posters/animated.gif", self.storage)

        self.assertIsNone(convert_field(field))
        self.assertNotIn("posters/animated.webp", self.storage.files)

    def test_broken_file_does_not_raise(self):
        """
        Битая картинка не должна ронять сохранение записи: копия — это
        оптимизация, а не условие того, что фильм существует.
        """
        self.storage.files["posters/broken.jpg"] = "это не картинка".encode("utf-8")
        field = FakeField("posters/broken.jpg", self.storage)

        self.assertIsNone(convert_field(field))

    def test_empty_field_is_ignored(self):
        self.assertIsNone(convert_field(FakeField("", self.storage)))


class WebpNameTests(TestCase):
    def test_replaces_suffix(self):
        self.assertEqual(webp_name("posters/2026/08/a.jpg"), "posters/2026/08/a.webp")
        self.assertEqual(webp_name("a.PNG"), "a.webp")


class WebpUrlFilterTests(TestCase):
    """Миниатюра должна получать уменьшенную копию, а не самый большой файл.

    Поводом был замер боевого сайта: миниатюра 54×64 в сайдбаре просила
    полный WebP и в одном случае тянула 1.6 МБ, тогда как рядом лежала
    копия в 200px весом 15 КБ. Фильтр умел отдавать только полный файл,
    поэтому ширина стала его вторым аргументом.
    """

    def setUp(self):
        # Наличие копии фильтр держит в общем кэше по имени файла — между
        # тестами он переносится, и второй тест с тем же именем видел бы
        # ответ первого. В бою хранилище одно, там это как раз и нужно.
        cache.clear()
        self.storage = MemoryStorage()
        self.storage.files["posters/film.jpg"] = jpeg_bytes()
        self.storage.files["posters/film.webp"] = b"full"
        self.storage.files["posters/film-200w.webp"] = b"small"
        self.field = FakeField("posters/film.jpg", self.storage)

    def test_width_picks_smaller_copy(self):
        self.assertEqual(webp_url(self.field, 200), "https://bucket.example/posters/film-200w.webp")

    def test_without_width_behaviour_is_unchanged(self):
        self.assertEqual(webp_url(self.field), "https://bucket.example/posters/film.webp")

    def test_missing_sized_copy_falls_back_to_full_webp(self):
        """Нет нарезки (старые загрузки) — отдаём полный WebP, а не оригинал."""
        self.assertEqual(webp_url(self.field, 640), "https://bucket.example/posters/film.webp")

    def test_garbage_width_does_not_break_the_page(self):
        """Ширина из шаблона может прийти чем угодно: \"\" , None, текстом."""
        for bad in ("", None, "жж", 0, -5):
            self.assertEqual(webp_url(self.field, bad), "https://bucket.example/posters/film.webp")

    def test_no_webp_at_all_returns_original(self):
        storage = MemoryStorage()
        storage.files["posters/film.jpg"] = jpeg_bytes()
        field = FakeField("posters/film.jpg", storage)
        self.assertEqual(webp_url(field, 200), "https://bucket.example/posters/film.jpg")

    def test_empty_field_returns_nothing(self):
        self.assertEqual(webp_url(FakeField("", self.storage), 200), "")


class SidebarThumbnailTests(TestCase):
    """Проверка на живом шаблоне: разметку берём из сайдбара, а не из головы.

    Фильтр может быть прав, а шаблон — по-прежнему просить полный файл:
    именно это и было. Здесь страница собирается настоящей системой
    шаблонов с настоящим хранилищем, и мы смотрим, какой адрес ушёл
    в разметку миниатюры 54×64.
    """

    def setUp(self):
        cache.clear()
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        settings_override = override_settings(MEDIA_ROOT=self.media)
        settings_override.enable()
        self.addCleanup(settings_override.disable)

        folder = os.path.join(self.media, "posters", "2026", "10")
        os.makedirs(folder, exist_ok=True)
        for name in ("film.jpg", "film.webp", "film-200w.webp"):
            with open(os.path.join(folder, name), "wb") as handle:
                handle.write(b"\xff\xd8\xff")

        self.title = Title(
            name="Проверка",
            slug="proverka-miniatyury",
            status=Title.Status.PUBLISHED,
            type=Title.Type.MOVIE,
        )
        self.title.poster.name = "posters/2026/10/film.jpg"

    def rendered(self):
        return render_to_string("includes/lb_sidebar.html", {"coming_soon": [self.title]})

    def test_sidebar_thumbnail_asks_for_small_copy(self):
        html = self.rendered()
        self.assertIn("sb-films__poster", html)
        self.assertIn("posters/2026/10/film-200w.webp", html)
        self.assertNotIn('src="/media/posters/2026/10/film.webp"', html)

    def test_thumbnail_falls_back_when_no_small_copy(self):
        os.remove(os.path.join(self.media, "posters", "2026", "10", "film-200w.webp"))
        html = self.rendered()
        self.assertIn("posters/2026/10/film.webp", html)

    def test_no_year_does_not_print_none(self):
        """У записи без года в разметке стояло слово None.

        Шаблон печатал поле напрямую, а у пустого значения это его строковое
        представление — «None», а не пустота. Такие записи в каталоге есть
        (импорт без года выпуска), а в сайдбаре строка с годом — самая
        заметная часть строки фильма.
        """
        html = self.rendered()
        self.assertNotIn("None", html)

    def test_year_is_shown_when_present(self):
        self.title.release_year = 2010
        html = self.rendered()
        self.assertIn("2010", html)


class MediaFilesTestCase(TestCase):
    """Файлы в MEDIA_ROOT и заготовки записей для проверок на страницах.

    Имена файлов выдуманные, поэтому в разметке сразу видно, какую копию
    попросил шаблон. Байты при этом можно писать любые: превращать картинки
    в WebP в тестах незачем — проверяется выбор адреса, а не кодирование.
    """

    def setUp(self):
        cache.clear()
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        settings_override = override_settings(MEDIA_ROOT=self.media)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.wrote(
            "people/actor.jpg",
            "people/actor.webp",
            "people/actor-100w.webp",
            "people/actor-200w.webp",
        )
        self.wrote("covers/pack.jpg", "covers/pack.webp", "covers/pack-400w.webp", "covers/pack-800w.webp")
        self.wrote(
            "avatars/reader.jpg",
            "avatars/reader.webp",
            "avatars/reader-100w.webp",
            "avatars/reader-200w.webp",
        )
        self.wrote(
            "posters/hero.jpg",
            "posters/hero.webp",
            "posters/hero-200w.webp",
            "posters/hero-400w.webp",
            "posters/hero-640w.webp",
        )

    def wrote(self, *names):
        for name in names:
            path = os.path.join(self.media, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(b"\xff\xd8\xff")

    def person_with_photo(self, **kwargs):
        person = create_person(**kwargs)
        person.photo.name = "people/actor.jpg"
        person.save(update_fields=["photo"])
        return person

    def logged_in_user_with_avatar(self):
        """Аватар виден только вошедшему: у гостя в шапке стоит иконка."""
        user = create_user()
        user.avatar.name = "avatars/reader.jpg"
        user.save(update_fields=["avatar"])
        self.client.force_login(user)
        return user


class SmallSlotTests(MediaFilesTestCase):
    """Маленький слот просит копию под свой размер, а не файл с камеры.

    Проверяем на настоящих страницах: кружки человека и пользователя
    (28–88px) в поиске, составе фильма, шапке и профиле, а также обложка
    подборки в карточке (16:9, до ~400px). Все они раньше просили полный
    файл: у кружка — сотни килобайт на 36px, у карточки — обложка 16:9,
    которую показывают в треть экрана.
    """

    def test_person_avatar_in_search_asks_for_small_copy(self):
        person = self.person_with_photo(name="Аркадий Проверкин")
        create_participation(person=person)

        html = self.client.get("/search/", {"q": "Проверкин"}).content.decode("utf-8", "ignore")
        self.assertIn("avatar__image", html)
        self.assertIn("people/actor-100w.webp", html)

    def test_person_avatar_in_cast_list_asks_for_small_copy(self):
        """Состав фильма: кружок 36px, а в разметку шёл файл с камеры."""
        title = create_title()
        create_participation(title=title, person=self.person_with_photo())

        html = self.client.get(f"/title/{title.slug}/").content.decode("utf-8", "ignore")
        self.assertIn("people/actor-100w.webp", html)
        self.assertNotIn('src="/media/people/actor.jpg"', html)

    def test_person_list_asks_for_small_copy(self):
        # Витрина актёров показывает только тех, у кого есть роль.
        create_participation(person=self.person_with_photo())

        html = self.client.get("/actors/").content.decode("utf-8", "ignore")
        self.assertIn("avatar__image", html)
        self.assertIn("people/actor-100w.webp", html)

    def test_large_person_avatar_asks_for_bigger_copy(self):
        """Кружок 88px на странице персоны: нужен 200px, а не 100px."""
        person = self.person_with_photo()

        html = self.client.get(f"/persons/{person.slug}/").content.decode("utf-8", "ignore")
        self.assertIn("people/actor-200w.webp", html)

    def test_actor_search_photo_asks_for_small_copy(self):
        create_participation(person=self.person_with_photo(name="Аркадий Проверкин"))

        html = self.client.get("/search-by-actor/", {"q": "Проверкин"}).content.decode("utf-8", "ignore")
        self.assertIn("people/actor-100w.webp", html)

    def test_header_avatar_asks_for_small_copy(self):
        self.logged_in_user_with_avatar()

        html = self.client.get("/").content.decode("utf-8", "ignore")
        self.assertIn("avatars/reader-100w.webp", html)
        self.assertNotIn('src="/media/avatars/reader.jpg"', html)

    def test_profile_avatar_asks_for_bigger_copy(self):
        self.logged_in_user_with_avatar()

        html = self.client.get("/profile/").content.decode("utf-8", "ignore")
        self.assertIn("avatars/reader-200w.webp", html)

    def test_collection_card_asks_for_small_cover(self):
        collection = create_collection()
        collection.cover.name = "covers/pack.jpg"
        collection.save(update_fields=["cover"])

        html = self.client.get("/collections/").content.decode("utf-8", "ignore")
        self.assertIn("collection-card__image", html)
        self.assertIn("covers/pack-400w.webp", html)

    def test_pipeline_makes_the_copies_these_slots_ask_for(self):
        """Слот просит ширину — значит make_webp должен её создавать.

        Именно это расхождение и было: шаблон просит 200px, а нарезки для
        полей персон не заведено, и просьба молча упиралась в полный файл.
        """
        for key, width in (
            (("catalog.Title", "poster"), 200),
            (("catalog.Title", "poster"), 640),
            (("catalog.Title", "backdrop"), 1280),
            (("catalog.Collection", "cover"), 400),
            (("catalog.Collection", "cover"), 800),
            (("catalog.Person", "photo"), 100),
            (("catalog.Person", "photo"), 200),
            (("users.User", "avatar"), 100),
            (("users.User", "avatar"), 200),
        ):
            with self.subTest(field=key, width=width):
                self.assertIn(width, SIZED_VARIANTS.get(key, ()))


# sizes повторяют вёрстку: у постерa в шапке фильма 280px до 900px и 160px
# ниже, у обложки подборки — 240px рядом с текстом и вся ширина в колонке.
title_hero_sizes = "(min-width: 901px) 280px, 160px"
collection_hero_sizes = "(min-width: 721px) 240px, 100vw"


class FullFileSlotTests(MediaFilesTestCase):
    """Слот, который просил полный файл, обязан предлагать нарезку.

    Два самых заметных места страниц: постер в шапке фильма (280px
    на настольном экране, 160px на телефоне) и обложка в шапке подборки
    (240px рядом с текстом, во всю ширину на узком экране). Обе просили
    файл в натуральную величину — у одного постера это 1.6 МБ на картинку,
    которую показывают в 280px. Здесь стережётся не только адрес, но
    и sizes: без него браузер не знает, сколько места займёт картинка,
    и снова берёт самый большой кандидат.
    """

    def test_title_hero_poster_offers_sized_copies(self):
        title = create_title()
        title.poster.name = "posters/hero.jpg"
        title.save(update_fields=["poster"])

        html = self.client.get(f"/title/{title.slug}/").content.decode("utf-8", "ignore")
        self.assertIn("film-hero__poster-image", html)
        self.assertIn(f'sizes="{title_hero_sizes}"', html)
        self.assertIn("posters/hero-640w.webp", html)
        self.assertNotIn('src="/media/posters/hero.webp"', html)

    def test_collection_hero_offers_sized_copies(self):
        collection = create_collection()
        collection.cover.name = "covers/pack.jpg"
        collection.save(update_fields=["cover"])

        html = self.client.get(f"/collections/{collection.slug}/").content.decode("utf-8", "ignore")
        self.assertIn("collection-hero__image", html)
        self.assertIn(f'sizes="{collection_hero_sizes}"', html)
        self.assertIn("covers/pack-800w.webp", html)

    def test_title_hero_poster_falls_back_to_full_webp(self):
        """Без нарезки (старые загрузки) поведение прежнее: полный WebP."""
        for name in ("posters/hero-200w.webp", "posters/hero-400w.webp", "posters/hero-640w.webp"):
            os.remove(os.path.join(self.media, name))
        cache.clear()
        title = create_title()
        title.poster.name = "posters/hero.jpg"
        title.save(update_fields=["poster"])

        html = self.client.get(f"/title/{title.slug}/").content.decode("utf-8", "ignore")
        self.assertIn("posters/hero.webp", html)
        # Кандидат один — размеры ему не нужны, и их нет: sizes появляется
        # только там, где браузеру есть из чего выбирать.
        self.assertNotIn(f'sizes="{title_hero_sizes}"', html)
