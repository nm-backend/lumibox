from django import forms
from django.conf import settings
from django.core.cache import cache
from django.db.models import F, Q

from apps.catalog.models import Country, Genre, Title, VoiceOver

# Ключ кэша списка годов. Константа: сбрасывать его нужно из signals.py.
YEAR_CHOICES_CACHE_KEY = "catalog:year_choices:v1"

# Сортировки каталога: ключ — значение для order_by, значение — подпись.
#
# Единственное описание на весь проект. Раньше их было три: выпадающий
# список формы, панель быстрых сортировок каталога и панель на главной —
# с разным составом и даже с разной формой кортежа. Добавить сортировку
# значило вспомнить про все три места; забыть одно было легче лёгкого.
SORT_OPTIONS = {
    "-published_at": "По дате обновления",
    "-views_count": "По популярности (просмотры)",
    "-rating_average": "По рейтингу",
    "-release_year": "Сначала новые",
    "release_year": "Сначала старые",
    "name": "По алфавиту",
    # «Обсуждаемое»: сначала самые оценённые — у них больше всего голосов.
    "-rating_count": "По оценкам",
}

# Что показываем отдельными кнопками (а не в выпадающем списке).
# Пустая строка — сортировка по умолчанию, «по дате обновления».
QUICK_SORTS = [
    ("", "По дате обновления"),
    ("-views_count", "По просмотрам"),
    ("-rating_average", "По рейтингу"),
    ("-release_year", "По году"),
]


def get_year_choices():
    """
    Годы для выпадающего списка — только те, что реально есть в каталоге.

    Функция, а не готовый список: Django вызовет её при отрисовке формы.
    Иначе годы посчитались бы один раз при запуске и устарели бы
    после добавления новых фильмов.

    Результат кэшируем: Django обращается к choices дважды за запрос —
    при валидации и при отрисовке, — и без кэша каталог делал бы
    два одинаковых DISTINCT-запроса на каждой загрузке.
    Кэш сбрасывает тот же сигнал, что и кэш главной.
    """
    cached = cache.get(YEAR_CHOICES_CACHE_KEY)
    if cached is not None:
        return cached

    years = (
        Title.objects.published()
        .values_list("release_year", flat=True)
        .distinct()
        .order_by("-release_year")
    )
    choices = [("", "Любой год")] + [(str(year), str(year)) for year in years]

    cache.set(YEAR_CHOICES_CACHE_KEY, choices, settings.CACHE_TTL_HOME)
    return choices


class CatalogFilterForm(forms.Form):
    """
    Фильтры каталога.

    Форма не только рисует поля, но и умеет фильтровать queryset.
    Так вся логика отбора лежит в одном месте, а вьюха остаётся тонкой.
    Все поля необязательные: каталог должен открываться без параметров.
    """

    q = forms.CharField(
        label="Поиск",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Название"}),
    )
    type = forms.ChoiceField(
        label="Тип",
        required=False,
        choices=[("", "Всё")] + Title.Type.choices,
    )
    genre = forms.ModelChoiceField(
        label="Жанр",
        required=False,
        queryset=Genre.objects.all(),
        # Ищем жанр по slug, а не по id: адрес /catalog/?genre=drama
        # читается человеком и не ломается при переносе базы.
        to_field_name="slug",
        empty_label="Все жанры",
    )
    country = forms.ModelChoiceField(
        label="Страна",
        required=False,
        queryset=Country.objects.all(),
        to_field_name="slug",
        empty_label="Все страны",
    )
    year = forms.ChoiceField(
        label="Год",
        required=False,
        choices=get_year_choices,
    )
    # Диапазон лет — рядом с точным годом, а не вместо него: ссылки вида
    # ?year=2019 уже разошлись по сайту и по внешним переходам.
    year_from = forms.IntegerField(
        label="Год: с",
        required=False,
        min_value=1888,
        max_value=2100,
        widget=forms.NumberInput(attrs={"placeholder": "1990"}),
    )
    year_to = forms.IntegerField(
        label="Год: по",
        required=False,
        min_value=1888,
        max_value=2100,
        widget=forms.NumberInput(attrs={"placeholder": "2026"}),
    )
    rating_from = forms.DecimalField(
        label="Рейтинг от",
        required=False,
        min_value=0,
        max_value=10,
        max_digits=3,
        decimal_places=1,
        widget=forms.NumberInput(attrs={"step": "0.5", "placeholder": "7"}),
    )
    quality = forms.ChoiceField(
        label="Качество",
        required=False,
        choices=[("", "Любое")] + Title.Quality.choices,
    )
    age_rating = forms.ChoiceField(
        label="Возраст",
        required=False,
        choices=[("", "Любой")] + Title.AgeRating.choices,
    )
    voice = forms.ModelChoiceField(
        label="Озвучка",
        required=False,
        queryset=VoiceOver.objects.all(),
        to_field_name="slug",
        empty_label="Любая",
    )
    sort = forms.ChoiceField(
        label="Сортировка",
        required=False,
        choices=list(SORT_OPTIONS.items()),
    )

    def filter(self, queryset):
        """Применяет к queryset только те фильтры, которые заполнены."""
        if not self.is_valid():
            # Мусор в адресной строке не должен ломать каталог —
            # просто показываем всё без фильтров.
            return queryset

        data = self.cleaned_data

        if data.get("q"):
            queryset = queryset.filter(
                Q(name__icontains=data["q"]) | Q(original_name__icontains=data["q"])
            )

        if data.get("type"):
            queryset = queryset.filter(type=data["type"])

        if data.get("genre"):
            queryset = queryset.filter(genres=data["genre"])

        if data.get("country"):
            queryset = queryset.filter(countries=data["country"])

        if data.get("year"):
            queryset = queryset.filter(release_year=data["year"])

        # Границы диапазона независимы: можно задать только «с» или только «по».
        if data.get("year_from"):
            queryset = queryset.filter(release_year__gte=data["year_from"])

        if data.get("year_to"):
            queryset = queryset.filter(release_year__lte=data["year_to"])

        if data.get("rating_from"):
            queryset = queryset.filter(rating_average__gte=data["rating_from"])

        if data.get("quality"):
            queryset = queryset.filter(quality=data["quality"])

        if data.get("age_rating"):
            queryset = queryset.filter(age_rating=data["age_rating"])

        if data.get("voice"):
            # distinct() обязателен: у записи столько источников с этой
            # озвучкой, сколько серий, и без него фильм пришёл бы в список
            # по разу на каждую серию.
            queryset = queryset.filter(playback_sources__voice=data["voice"]).distinct()

        # order_by переопределяет сортировку из Meta модели.
        if data.get("sort"):
            queryset = self._apply_sort(queryset, data["sort"])

        return queryset

    def _apply_sort(self, queryset, sort):
        """
        Применяет сортировку.

        Рейтинг требует особого обращения: у неоценённых записей поле пустое,
        а PostgreSQL по умолчанию ставит NULL первыми при убывании — и каталог
        начинался бы с фильмов вообще без оценок. nulls_last это исправляет.
        """
        # «pk» в конце — тайбрейкер: год, имя и рейтинг неуникальны, а без
        # уникального последнего ключа PostgreSQL волен вернуть строки-близнецы
        # в разном порядке между страницами. Тогда один фильм показывается
        # дважды, а другой пропадает при листании.
        if sort == "-rating_average":
            return queryset.order_by(F("rating_average").desc(nulls_last=True), "-rating_count", "pk")

        return queryset.order_by(sort, "pk")

    def active_filter_labels(self):
        """
        Заполненные фильтры в виде пар (имя поля, подпись для человека).

        Поиск сюда не входит: он и так виден в строке поиска.
        Ссылку «убрать фильтр» строит вьюха — только у неё есть запрос.
        """
        if not self.is_valid():
            return []

        data = self.cleaned_data
        year_from, year_to = data.get("year_from"), data.get("year_to")
        rating_from = data.get("rating_from")

        labels = {
            "type": dict(Title.Type.choices).get(data.get("type")),
            "genre": getattr(data.get("genre"), "name", None),
            "country": getattr(data.get("country"), "name", None),
            "year": data.get("year"),
            "year_from": f"с {year_from}" if year_from else None,
            "year_to": f"по {year_to}" if year_to else None,
            "rating_from": f"рейтинг от {rating_from}" if rating_from else None,
            "quality": data.get("quality"),
            "age_rating": data.get("age_rating"),
            "voice": getattr(data.get("voice"), "name", None),
        }
        return [(field, label) for field, label in labels.items() if label]
