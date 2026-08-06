#!/usr/bin/env python3
"""Запрещает возвращение брендинга Kinogo в код и разметку.

Проект переименован: классы dle-*/kg-* стали lb-*, файлы kinogo.css
и kg_sidebar.html — lumibox.css и lb_sidebar.html. Хук ловит рецидивы
в изменяемых файлах при коммите.

Запуск: python scripts/check_branding.py [файлы...]
Возвращает ненулевой код, если найден запрещённый токен.
"""

import os
import sys

FORBIDDEN = ("kg-", "kg_", "kinogo", "Kinogo")

_SELF = os.path.abspath(__file__)


def main(filenames):
    bad = []
    for name in filenames:
        # Сам скрипт обязан содержать запрещённые токены — они описаны
        # в его докстроке и FORBIDDEN. Проверять себя бессмысленно.
        if os.path.abspath(name) == _SELF:
            continue
        try:
            with open(name, encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        for token in FORBIDDEN:
            if token in content:
                bad.append((name, token))
    if bad:
        for name, token in bad:
            print(f"{name}: найден запрещённый токен {token!r}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
