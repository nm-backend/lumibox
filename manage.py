#!/usr/bin/env python
"""Утилита командной строки Django для административных задач."""

import os
import sys


# ---------------------------------------------------------------------------
# Python 3.14 compatibility: Django 5.1's BaseContext.__copy__ uses
# copy(super()) which broke in Python 3.14.  Patch it before anything else.
# ---------------------------------------------------------------------------
def _patch_django_context():
    try:
        from django.template.context import BaseContext

        def _patched_copy(self):
            # Python 3.14: copy(super()) returns a bare super() proxy instead
            # of the actual instance, so duplicate.dicts = … fails with
            # AttributeError.  Build the copy manually.
            duplicate = object.__new__(self.__class__)
            duplicate.__dict__.update(self.__dict__)
            duplicate.dicts = self.dicts[:]
            return duplicate

        BaseContext.__copy__ = _patched_copy
    except ImportError:
        pass  # Django not yet installed — will be patched on next call


_patch_django_context()
# ---------------------------------------------------------------------------


def main():
    # manage.py — инструмент разработчика, поэтому по умолчанию берём
    # настройки разработки. Переменная окружения, если она задана, важнее.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Не удалось импортировать Django. Он установлен? "
            "Виртуальное окружение активировано?"
        ) from exc

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
