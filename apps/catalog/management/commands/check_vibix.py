"""
Проверка интеграции с видеосервисом Vibix.

Проверяет credentials, connectivity, и что API отдаёт валидный embed_code.
Запускается как часть preflight или вручную:

    python manage.py check_vibix

Возвращает ненулевой код при сбое — подходит как шаг в пайплайне выкладки.
Если credentials не заданы — сообщает об этом, но НЕ падает:
сайт без Vibix работает (YouTube/local fallback).
"""

import re

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.catalog.video_service_api import (
    VideoServiceAPIError,
    VideoServiceAuthenticationError,
    get_vibix_api_token,
    iter_video_links,
)


class Check:
    """Результат одной проверки."""

    def __init__(self, name, ok, detail, required=False):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.required = required


class Command(BaseCommand):
    help = "Проверяет credentials и API connectivity Vibix."

    def handle(self, *args, **options):
        checks = [
            self._check_credentials(),
            self._check_publisher_id(),
            self._check_api_connectivity(),
            self._check_embed_code(),
        ]

        failed = [c for c in checks if not c.ok and c.required]
        warned = [c for c in checks if not c.ok and not c.required]

        width = max(len(c.name) for c in checks)
        for c in checks:
            if c.ok:
                mark, style = "OK  ", self.style.SUCCESS
            elif c.required:
                mark, style = "СБОЙ", self.style.ERROR
            else:
                mark, style = "ВНИМ", self.style.WARNING
            self.stdout.write(style(f"[{mark}] {c.name.ljust(width)}  {c.detail}"))

        self.stdout.write("")
        if failed:
            self.stderr.write(
                self.style.ERROR(f"Не прошло обязательных проверок: {len(failed)}.")
            )
            raise SystemExit(1)

        tail = f" Предупреждений: {len(warned)}." if warned else ""
        self.stdout.write(self.style.SUCCESS(f"Vibix готово.{tail}"))

    def _check_credentials(self):
        token = get_vibix_api_token()
        if not token:
            return Check(
                "API Token",
                False,
                "VIBIX_API_TOKEN не задан — Vibix отключён (YouTube/local fallback работает)",
                required=False,
            )
        if len(token) < 10:
            return Check("API Token", False, "Токен слишком короткий", required=True)
        return Check("API Token", True, f"токен задан ({len(token)} символов)")

    def _check_publisher_id(self):
        publisher_id = getattr(settings, "VIBIX_PUBLISHER_ID", "").strip()
        if not publisher_id:
            return Check(
                "Publisher ID",
                False,
                "VIBIX_PUBLISHER_ID не задан — плеер не будет рендериться",
                required=False,
            )
        if not publisher_id.isdigit():
            return Check(
                "Publisher ID", False, "Publisher ID должен быть числом", required=True
            )
        return Check("Publisher ID", True, f"задан: {publisher_id}")

    def _check_api_connectivity(self):
        token = get_vibix_api_token()
        if not token:
            return Check(
                "API Connectivity",
                False,
                "пропускается (нет токена)",
                required=False,
            )
        try:
            items = list(iter_video_links(token, limit=20, max_pages=1))
        except VideoServiceAuthenticationError as e:
            return Check(
                "API Connectivity",
                False,
                f"аутентификация не прошла: {e}",
                required=True,
            )
        except VideoServiceAPIError as e:
            return Check(
                "API Connectivity", False, f"ошибка API: {e}", required=True
            )
        except Exception as e:
            return Check(
                "API Connectivity",
                False,
                f"неожиданная ошибка: {type(e).__name__}: {e}",
                required=True,
            )
        if not items:
            return Check("API Connectivity", True, "API доступен, каталог пуст")
        return Check(
            "API Connectivity", True,
            f"API доступен, авторизация прошла ({len(items)} записей)",
        )

    def _check_embed_code(self):
        """Проверяет, что хотя бы одна запись API содержит embed_code с data-id."""
        token = get_vibix_api_token()
        if not token:
            return Check(
                "Embed Code",
                False,
                "пропускается (нет токена)",
                required=False,
            )
        try:
            found = False
            for item in iter_video_links(token, limit=50, max_pages=1):
                embed_code = item.get("embed_code") or ""
                match = re.search(r'data-id="(\d+)"', embed_code)
                if match:
                    player_id = match.group(1)
                    return Check(
                        "Embed Code",
                        True,
                        f"найден data-id={player_id} в catalog API",
                    )
                found = True
            if found:
                return Check(
                    "Embed Code",
                    False,
                    "API доступен, но ни одна запись не содержит data-id в embed_code",
                    required=False,
                )
            return Check(
                "Embed Code",
                False,
                "каталог API пуст",
                required=False,
            )
        except VideoServiceAPIError as e:
            return Check(
                "Embed Code", False, f"ошибка API: {e}", required=False
            )
        except Exception as e:
            return Check(
                "Embed Code",
                False,
                f"неожиданная ошибка: {type(e).__name__}: {e}",
                required=False,
            )
