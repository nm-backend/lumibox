"""
Русский текст отказов API там, где фреймворк отвечает по-английски.

И Django, и DRF на «ничего не найдено» подставляют служебную фразу, которую
никто не переводит: get_object_or_404 и get_object() поднимают
Http404('No Title matches the given query.') — то есть клиент получал не
ответ, а обрывок внутреннего устройства с именем модели. Так же уходит
английская подсказка при отказе проверки CSRF: «CSRF Failed: CSRF cookie
not set.»

Правим это в одном месте: обработчик подключён настройкой EXCEPTION_HANDLER,
поэтому под него попадают и сегодняшние вьюхи, и те, что появятся позже.
Вьюха, которая знает, о какой сущности речь, по-прежнему может отдать свой
текст сама — как RateTitleView отдаёт «Запись не найдена.».
"""

from django.http import Http404
from rest_framework import exceptions
from rest_framework.views import exception_handler

NOT_FOUND_DETAIL = "Ничего не найдено."
CSRF_DETAIL = "Проверка безопасности не пройдена. Обновите страницу и повторите запрос."


def _is_csrf(exc):
    """
    Отказ по CSRF DRF помечает текстом «CSRF Failed: ...».

    Отдельного класса для него нет, а detail бывает и списком — приводим
    к строке и ищем метку.
    """
    detail = getattr(exc, "detail", "")
    if isinstance(detail, (list, tuple)):
        detail = " ".join(str(item) for item in detail)
    return "CSRF" in str(detail)


def api_exception_handler(exc, context):
    """
    Стандартный обработчик DRF плюс русские тексты вместо английских.

    Принимает: исключение и контекст вьюхи, как у DRF.
    Возвращает: Response либо None, если ответ формирует Django (ошибка
    уровня 500 остаётся за обработчиком проекта).
    """
    response = exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, Http404):
        response.data = {"detail": NOT_FOUND_DETAIL}
    elif isinstance(exc, exceptions.PermissionDenied) and _is_csrf(exc):
        response.data = {"detail": CSRF_DETAIL}

    return response
