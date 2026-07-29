"""
Python 3.14 workaround for Django's template context __copy__.

Django 5.2.16 использует super().__copy__() в BaseContext.__copy__,
что ломается на Python 3.14.14+: super.__copy__ возвращает прокси-объект
вместо настоящей копии, и атрибут .dicts не может быть установлен.

Импортировать этот модуль ДО начала рендеринга шаблонов — оптимально
в самом конце config/settings/base.py или в файлах, которым нужен fix.

TODO: Убрать после обновления Django до версии с фиксом.
"""

from __future__ import annotations

import copy

import django.template.context as _ctx


def _safe_context_copy(self):
    duplicate = object.__new__(type(self))
    duplicate.__dict__.update(self.__dict__)
    duplicate.dicts = self.dicts[:]
    return duplicate


# Регистрируем кастомный __copy__ для BaseContext и всех его подклассов
# (RenderContext, RequestContext).
_ctx.BaseContext.__copy__ = _safe_context_copy

# Также регистрируем в _copy_dispatch, если он существует (Python < 3.14
# использует этот диспатч для оптимизации).
if hasattr(copy, "_copy_dispatch"):
    copy._copy_dispatch[_ctx.BaseContext] = _safe_context_copy
