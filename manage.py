#!/usr/bin/env python
"""Утилита командной строки Django для административных задач."""

import os
import sys


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
