"""
Security and observability middleware for LumiBox.

Defense-in-depth headers that complement Django's built-in protections.
These are not a substitute for correct CSRF, XSS, and clickjacking handling,
but they raise the bar for an attacker who finds a bypass.
"""

import contextvars
import logging
import uuid

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

    If a feature on the site stops working, check the browser console
    for CSP violation reports before loosening the policy.
    """

    CSP_TEMPLATE = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://www.googletagmanager.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' https://www.google-analytics.com https://www.googletagmanager.com; "
        "frame-src 'self' https://www.youtube.com https://player.vimeo.com https://rutube.ru; "
        "media-src 'self' https:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Content-Security-Policy"] = self.CSP_TEMPLATE
        return response
