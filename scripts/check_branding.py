#!/usr/bin/env python3
"""Запрещает возвращение чужого брендинга в код и разметку.

Проект переименован: классы dle-*/kg-* стали lb-*, файлы с прежними
именами — lumibox.css и lb_sidebar.html. Хук ловит рецидивы в изменяемых
файлах при коммите.

Сравнение регистронезависимое. Прежний список перечислял варианты написания
руками и поэтому пропустил заголовок секции, набранный заглавными: строка
прожила в static/css/lumibox.css несколько коммитов, и хук её не замечал.
Кириллическая запись ловится отдельно по той же причине — её невозможно
получить из латинского написания приведением регистра.

Запуск: python scripts/check_branding.py [файлы...]
Возвращает ненулевой код, если найден запрещённый токен.
"""

import os
import sys

# В нижнем регистре: сравниваем с content.lower(), поэтому «KINOGO»,
# «Kinogo» и «kInOgO» ловятся одним элементом списка.
FORBIDDEN = (
    "kg-",
    "kg_",
    "kinogo",
    # Кириллическая запись того же названия и производные от неё
    # («кинго-карточка», «в стиле кинго») — из латиницы регистром не выводятся.
    "кинго",
)

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
                content = f.read().lower()
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
