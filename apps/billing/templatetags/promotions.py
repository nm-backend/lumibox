"""
Партнёрские баннеры на витрине.

Раньше рекламные блоки были нарисованными заглушками со ссылкой «#»: посетитель
видел рекламу, на которую нельзя нажать. Модель Promotion при этом существовала,
но с шаблонами связана не была.

Теперь баннеры ведутся из админки: раздел «Партнёрские баннеры». Не заполнено
ни одного активного — блок не выводится совсем, и пустого места на странице не
остаётся.
"""

from django import template
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from apps.billing.models import Promotion

register = template.Library()

PROMOTIONS_CACHE_KEY = "billing:promotions:{placement}:v1"

# Пять минут. Баннеры меняются редко, а запрос иначе выполнялся бы на каждой
# странице сайта. Правка в админке видна сразу и не ждёт эти пять минут:
# её сбрасывает сигнал (apps/billing/signals.py). TTL нужен только чтобы
# баннер с истёкшей датой показа ушёл сам, без правки в админке.
PROMOTIONS_CACHE_TTL = 60 * 5

# Какое размещение показывать, если тег позвали без аргумента.
# Ключ — имя маршрута, значение — вариант из Promotion.Placement.
_PLACEMENT_BY_URL_NAME = {
    "home": Promotion.Placement.HOME,
    "title_detail": Promotion.Placement.DETAIL,
}


def _placement_from_request(request):
    """Главная, карточка произведения или всё остальное — каталог."""
    url_name = getattr(getattr(request, "resolver_match", None), "url_name", None)
    return _PLACEMENT_BY_URL_NAME.get(url_name, Promotion.Placement.CATALOG)


def get_active_promotions(placement, limit):
    """
    Действующие баннеры для размещения, в порядке от свежих к старым.

    Окно показа проверяем запросом, а не свойством is_current в Python:
    иначе пришлось бы вычитать всю таблицу баннеров на каждой странице,
    чтобы отобрать из неё один-два.

    Возвращает список (не QuerySet): он кладётся в кэш, а ленивый запрос
    в кэше означал бы поход в базу у каждого, кто этот кэш прочитал.
    """
    key = PROMOTIONS_CACHE_KEY.format(placement=placement)
    cached = cache.get(key)
    if cached is None:
        now = timezone.now()
        cached = list(
            Promotion.objects.filter(is_active=True, placement=placement)
            .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
            .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
            .order_by("-created_at")[:4]
        )
        cache.set(key, cached, PROMOTIONS_CACHE_TTL)
    return cached[:limit]


@register.inclusion_tag("includes/ad_rail.html", takes_context=True)
def ad_rail(context, placement=None):
    """Боковые баннеры: до двух штук, левый и правый."""
    placement = placement or _placement_from_request(context.get("request"))
    banners = get_active_promotions(placement, limit=2)
    return {
        "left": banners[0] if banners else None,
        # Правый показываем только если баннеров действительно два:
        # один и тот же баннер с обеих сторон выглядел бы ошибкой вёрстки.
        "right": banners[1] if len(banners) > 1 else None,
    }


@register.inclusion_tag("includes/ad_block.html", takes_context=True)
def ad_block(context, placement=None):
    """Горизонтальный баннер между блоками контента."""
    placement = placement or _placement_from_request(context.get("request"))
    banners = get_active_promotions(placement, limit=1)
    return {"promotion": banners[0] if banners else None}
