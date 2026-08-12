"""Фильтры шаблонов каталога для главной страницы."""

from datetime import timedelta

from django import template
from django.core.cache import cache
from django.utils import timezone
from django.utils.translation import gettext

register = template.Library()

# Наличие WebP-копии меняется только при загрузке новой картинки, поэтому
# держим ответ сутки.
WEBP_CHECK_TTL = 60 * 60 * 24


def _has_webp(storage, name: str) -> bool:
    """
    Есть ли WebP-копия рядом с оригиналом.

    Ответ кладём в общий кэш, а не в lru_cache процесса. Два повода.

    Первый: на бакете storage.exists — это сетевой запрос. В сетке каталога
    восемнадцать постеров, и на холодном процессе страница стоила бы
    восемнадцати обращений к R2 ещё до первого байта ответа. Общий кэш
    делит их между всеми воркерами и переживает перезапуск.

    Второй: lru_cache ключевался в том числе объектом хранилища. У бакета
    экземпляр storage создаётся заново, и ключ не совпадал — кэш промахивался
    на каждом запросе, то есть не работал именно там, где был нужен.
    """
    if not name:
        return False
    base, _ = name.rsplit(".", 1) if "." in name else (name, "")
    target = f"{base}.webp"
    key = f"webp:{target}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        found = storage.exists(target)
    except (OSError, NotImplementedError):
        found = False
    cache.set(key, found, WEBP_CHECK_TTL)
    return found


@register.filter
def webp_url(value):
    """URL WebP-версии изображения, если она существует, иначе оригинал.

    WebP-копии создаются сигналом при сохранении (apps.catalog.webp),
    весят в ~3 раза меньше JPG. Использование: {{ title.poster|webp_url }}.
    Ожидает ImageFieldFile; безопасен для пустых полей.
    """
    if not value or not getattr(value, "name", None):
        return ""
    if _has_webp(value.storage, value.name):
        base, _ = value.name.rsplit(".", 1)
        return value.storage.url(f"{base}.webp")
    return value.url


@register.filter
def webp_srcset(value):
    """
    Список уменьшенных копий для атрибута srcset.

    Возвращает строку вида «…-200w.webp 200w, …-400w.webp 400w, …webp 600w»
    или пустую строку, если копий нет. Пустой srcset безопасен: браузер
    возьмёт то, что в src.

    Зачем: постер в сетке каталога занимает 132–200px, то есть до 400px на
    экране с удвоенной плотностью. Без srcset туда уезжает картинка
    в 600px и шире — и байты за неё платит телефон на мобильной сети.

    Набор доступных ширин кладём в общий кэш одной записью: иначе каждая
    карточка стоила бы трёх обращений к бакету вместо одного.
    """
    if not value or not getattr(value, "name", None):
        return ""

    from apps.catalog.webp import SIZED_VARIANTS, webp_name

    field = getattr(value, "field", None)
    model = getattr(getattr(field, "model", None), "_meta", None)
    if model is None or field is None:
        return ""
    key = (f"{model.app_label}.{model.object_name}", field.name)
    widths = SIZED_VARIANTS.get(key)
    if not widths:
        return ""

    cache_key = f"webp:srcset:{value.name}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    storage = value.storage
    parts = []
    for width in widths:
        candidate = webp_name(value.name, width)
        try:
            if storage.exists(candidate):
                parts.append(f"{storage.url(candidate)} {width}w")
        except (OSError, NotImplementedError):
            continue

    # Оригинальная копия замыкает список: её ширину знаем не всегда,
    # поэтому берём из поля, а без неё вовсе не добавляем — иначе браузер
    # получит кандидата без дескриптора и проигнорирует весь набор.
    original_width = getattr(value, "width", None)
    if parts and original_width:
        base = webp_name(value.name)
        try:
            url = storage.url(base) if storage.exists(base) else value.url
        except (OSError, NotImplementedError):
            url = value.url
        parts.append(f"{url} {original_width}w")

    result = ", ".join(parts)
    cache.set(cache_key, result, WEBP_CHECK_TTL)
    return result


@register.filter
def lb_posted(value):
    """Относительная дата публикации: «Сегодня, 14:05»,
    «Вчера, 22:31», для более старых записей — «31.07.2026, 20:33»."""
    if not value:
        return ""
    now = timezone.localtime(timezone.now())
    local = timezone.localtime(value)
    day = local.date()
    if day == now.date():
        label = gettext("Сегодня")
    elif day == now.date() - timedelta(days=1):
        label = gettext("Вчера")
    else:
        label = local.strftime("%d.%m.%Y")
    return f"{label}, {local.strftime('%H:%M')}"


@register.filter
def lb_timecode(value):
    """
    Секунды в вид «12:34» или «1:02:03».

    Нужен подписи «Продолжить с 12:34». Часы показываем только когда они
    есть: «0:12:34» на серии в двадцать минут выглядит бюрократично.
    """
    try:
        total = int(value)
    except (TypeError, ValueError):
        return ""
    if total < 0:
        return ""

    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


@register.filter
def ru_plural(value, forms):
    """Русские плюральные формы: «1 произведение, 2 произведения, 5 произведений».

    forms — три формы через запятую: "произведение,произведения,произведений".
    Стандартный фильтр pluralize в Django 5.2 поддерживает только две формы,
    поэтому для русского нужен свой: правило — 1 (но не 11) → первая форма,
    2–4 (но не 12–14) → вторая, остальное → третья.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return forms.split(",")[-1]
    one, few, many = forms.split(",")
    n10 = n % 10
    n100 = n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return few
    return many


@register.filter
def lb_crew(value, role):
    """Список имён съёмочной группы по роли: режиссёр, актёры и т.д.

    value — Title, role — строка-роль Participation.Role. Возвращает
    строку «Имя / Имя», ограниченную пятью именами, из prefetch'а
    participations — без новых запросов к базе."""
    if not value:
        return ""
    participations = getattr(value, "participations", None)
    if participations is None:
        return ""
    names = [
        p.person.name
        for p in participations.all()
        if p.role == role
    ]
    if not names:
        return ""
    return " / ".join(names[:5])
