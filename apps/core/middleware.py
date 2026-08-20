"""
Security and observability middleware for LumiBox.

Defense-in-depth headers that complement Django's built-in protections.
These are not a substitute for correct CSRF, XSS, and clickjacking handling,
but they raise the bar for an attacker who finds a bypass.
"""

import contextvars
import logging
import uuid

from django.conf import settings

# ID текущего запроса: middleware кладёт его в contextvar, лог-фильтр
# и Sentry (before_send) читают то же значение — каждый лог и событие
# об ошибке привязываются к конкретному запросу.
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


def get_request_id() -> str:
    """ID текущего запроса или '-' вне запроса (команды, celery-задачи)."""
    return _request_id_var.get()


class RequestIdFilter(logging.Filter):
    """Добавляет request_id в каждую запись лога."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class RequestIdMiddleware:
    """Присваивает запросу ID, отдаёт его в X-Request-ID и в логи.

    Пробрасывает входящий X-Request-ID (для связки с балансировщиком/CDN)
    или генерирует новый. Ответ всегда содержит X-Request-ID — по нему
    в логах ищут цепочку событий одного запроса.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.request_id = request_id
        token = _request_id_var.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            _request_id_var.reset(token)
        response["X-Request-ID"] = request_id
        return response


class ContentSecurityPolicyMiddleware:
    """
    Adds Content-Security-Policy header to every response.

    Policy is intentionally restrictive: scripts and connections only
    from the same origin. Inline styles are allowed because the admin
    and some libraries need them. Images can come from anywhere (posters
    may be served from a CDN or object storage).

    External exceptions, каждый с причиной:
    - googletagmanager / google-analytics — метрика;
    - graphicslab.io — SDK внешнего плеера; *.kinescopecdn.net и
      *.videoframe2.com — текущий и прежний iframe-контуры. SDK загружается
      только после нажатия зрителя на странице с заполненными ID; CSP лишь
      разрешает известные контуры и сама запросов не создаёт.
    - www.youtube.com — IFrame API и iframe плеера YouTube (вкладка
      «Смотреть фильм/серии»). frame-src уже был разрешён для трейлеров,
      script-src/connect-src нужны API ролика: он грузится лениво,
      только на страницах с YouTube-видео.

    If a feature on the site stops working, check the browser console
    for CSP violation reports before loosening the policy.
    """

    CSP_TEMPLATE = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' "
        "https://www.googletagmanager.com https://graphicslab.io "
        "https://sync.videoframe2.com https://www.youtube.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' https://www.google-analytics.com "
        "https://www.googletagmanager.com https://graphicslab.io "
        "https://*.kinescopecdn.net https://*.videoframe2.com "
        "https://sync.videoframe2.com wss://sync.videoframe2.com "
        "https://www.youtube.com; "
        "frame-src 'self' https://www.youtube.com https://player.vimeo.com "
        "https://rutube.ru https://*.kinescopecdn.net https://*.videoframe2.com; "
        "media-src 'self' https:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )

    # Дополнение к политике при включённой рекламной сети
    # (ADS_NETWORK_ENABLED=true). Лоадер и движок рекламы живут на этих
    # доменах; креативы, трекинг-пиксели и iframe форматов (стикеры, баннеры)
    # приходят с произвольных https-доменов рекламодателей, которые нельзя
    # перечислить заранее, поэтому frame-src и connect-src расширяются
    # до любых https-источников. Без этого реклама молча блокируется, как
    # блокировался бы SDK плеера. Когда флаг выключен, политика остаётся
    # строгой — этот блок не применяется вовсе.
    ADS_NETWORK_CSP_ADDITIONS = (
        "script-src https://v-js-menu.run https://cdn.timing-js-menu.xyz; "
        "connect-src https://vast2.ufouxbwn.com https://cdn7.ufouxbwn.com https:; "
        "frame-src https:; "
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Content-Security-Policy"] = self._policy()
        return response

    def _policy(self) -> str:
        """Политика с учётом включённой рекламной сети."""
        if not getattr(settings, "ADS_NETWORK_ENABLED", False):
            return self.CSP_TEMPLATE
        base = dict(
            directive.split(" ", 1)
            for directive in self.CSP_TEMPLATE.split("; ")
            if " " in directive
        )
        for addition in self.ADS_NETWORK_CSP_ADDITIONS.split("; "):
            if not addition:
                continue
            name, _, value = addition.partition(" ")
            if name in base:
                # Расширяем существующую директиву, не дублируя уже
                # присутствующие в ней источники.
                existing = set(base[name].split())
                merged = existing | set(value.split())
                base[name] = " ".join(sorted(merged))
            else:
                base[name] = value
        return "; ".join(f"{name} {value}" for name, value in base.items())

