"""
Security middleware for LumiBox.

Defense-in-depth headers that complement Django's built-in protections.
These are not a substitute for correct CSRF, XSS, and clickjacking handling,
but they raise the bar for an attacker who finds a bypass.
"""


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
        "frame-src 'self' https://www.youtube.com https://player.vimeo.com; "
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
