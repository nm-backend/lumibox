"""
Тесты дополнительных вьюх ядра: serve_public_media, ElidedPaginationMixin
и статические страницы.

Покрывает:
- serve_public_media — защита приватных медиафайлов
- ElidedPaginationMixin — структура контекста с пагинацией
- статические страницы — открываются и подключают свои стили
"""

from django.http import Http404, HttpRequest
from django.test import TestCase
from django.urls import reverse

from apps.core.test_factories import create_title
from apps.core.views import serve_public_media


class ServePublicMediaTests(TestCase):
    """serve_public_media не должен открывать приватные файлы."""

    def test_private_media_returns_404(self):
        """Путь, начинающийся с private_media/, должен вернуть 404."""
        request = HttpRequest()
        request.META = {"SERVER_NAME": "test", "SERVER_PORT": "80"}
        with self.assertRaises(Http404):
            serve_public_media(request, "private_media/videos/2025/01/video.mp4")

    def test_normal_media_raises_http404_not_blocked(self):
        """Обычный медиа-путь отдаёт 404 от serve(), не блок Http404."""
        request = HttpRequest()
        request.META["SERVER_NAME"] = "localhost"
        request.META["SERVER_PORT"] = "8000"
        with self.assertRaises(Http404):
            serve_public_media(request, "posters/poster.jpg", document_root="media")


class ElidedPaginationMixinTests(TestCase):
    """
    ElidedPaginationMixin кладёт в контекст готовый диапазон страниц.

    Раньше этот тест собирал Paginator руками и проверял его же вывод —
    то есть тестировал Django, а не миксин: удали миксин целиком, и тест
    остался бы зелёным. Теперь запрашиваем настоящую страницу каталога,
    который на миксине и построен.
    """

    @classmethod
    def setUpTestData(cls):
        # paginate_by = 24, поэтому 60 записей дают три страницы —
        # достаточно, чтобы диапазон схлопнулся с многоточием.
        for number in range(60):
            create_title(name=f"Фильм пагинации {number}")

    def test_context_has_elided_range_and_ellipsis(self):
        response = self.client.get(reverse("catalog:title_list"))

        self.assertIn("elided_page_range", response.context)
        self.assertIn("ellipsis", response.context)
        self.assertEqual(response.context["paginator"].num_pages, 3)

    def test_page_numbers_rendered(self):
        """Без миксина шаблон рисует только «Назад» и «Вперёд», без номеров."""
        response = self.client.get(reverse("catalog:title_list"))

        self.assertContains(response, "lb-pagination__current")
        self.assertContains(response, "lb-pagination__link")


class TemplateCommentSyntaxTests(TestCase):
    """
    Комментарий {# … #} обязан умещаться в одну строку.

    Django распознаёт эту форму только внутри строки: как только между {# и #}
    попадает перевод строки, текст перестаёт быть комментарием и печатается
    посетителю как есть. Многострочные пояснения пишутся через
    {% comment %} … {% endcomment %}.

    Проект уже наступал на это дважды: один раз в шапке с preload шрифтов,
    второй — в пояснениях к секции плеера, где слова из комментария попали
    в разметку и сломали проверку «плеера нет у записи без серий». Тест
    дешевле третьего раза.
    """

    def test_no_multiline_hash_comments(self):
        import pathlib
        import re

        templates_dir = pathlib.Path(__file__).resolve().parents[2] / "templates"
        offenders = []

        for path in sorted(templates_dir.rglob("*.html")):
            text = path.read_text(encoding="utf-8-sig")
            for match in re.finditer(r"\{#", text):
                start = match.start()
                close = text.find("#}", start)
                newline = text.find("\n", start)
                if close == -1 or (newline != -1 and newline < close):
                    line = text[:start].count("\n") + 1
                    offenders.append(f"{path.name}:{line}")

        self.assertEqual(
            offenders,
            [],
            "Многострочный {# #} рендерится как видимый текст. "
            f"Замените на {{% comment %}}: {', '.join(offenders)}",
        )


class StaticPagesTests(TestCase):
    """
    Правовые и справочные страницы: открываются и подключают свои стили.

    Их не покрывал ни один тест, и /faq/ месяцами открывалась неоформленной:
    классы .legal-* лежат в forms.css, а блок extra_css в шаблоне забыли.
    Проверяем не только код ответа, но и наличие таблицы стилей — иначе
    страница снова может «работать» и выглядеть сломанной.
    """

    LEGAL_PAGES = ["about", "copyright", "advertisers", "privacy", "terms", "contacts", "faq"]

    def test_pages_open(self):
        for name in self.LEGAL_PAGES:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_pages_load_their_stylesheet(self):
        for name in self.LEGAL_PAGES:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, "css/forms.css")
