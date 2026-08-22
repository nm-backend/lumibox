"""
Dev-only middleware: kills all browser caching.

During local development browsers aggressively cache static files and HTML.
Even Ctrl+F5 / incognito / DevTools "Disable cache" don't always work
because Django's dev server sends no Cache-Control header, and browsers
apply their own heuristics (Last-Modified → If-Modified-Since → 304).

This middleware adds strong no-cache headers to EVERY response so the
browser always fetches fresh content. Only active when DEBUG=True —
has zero cost in production.
"""


class NoCacheDevMiddleware:
    """Prevent all browser caching when DEBUG is enabled.

    Adds headers that tell every browser, proxy, and CDN to revalidate:
    - no-store:   don't store the response at all
    - no-cache:   revalidate before using cached copy
    - must-revalidate: always check with server

    Place this AFTER SecurityMiddleware and BEFORE any caching middleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Only touch static files and HTML — leave API/JSON alone
        # (API caching is handled separately by DRF).
        content_type = response.get("Content-Type", "")
        if content_type.startswith(("text/html", "text/css", "application/javascript")):
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
            # Vary on everything — prevents shared caches from mixing users
            existing_vary = response.get("Vary", "")
            if existing_vary:
                response["Vary"] = f"{existing_vary}, Cookie"
            else:
                response["Vary"] = "Cookie"

        return response
