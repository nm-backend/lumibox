/*
  Service Worker для MovieHub PWA.

  Кэширует статические ресурсы (CSS, JS, изображения)
  для офлайн-доступа и ускорения загрузки.

  Стратегия:
  - Статика: Cache First (из кэша, потом из сети)
  - Страницы: Network First (из сети, потом из кэша)
  - API: Network Only (всегда из сети)
*/

const CACHE_NAME = "moviehub-v1";
const STATIC_ASSETS = [
    "/static/css/variables.css",
    "/static/css/base.css",
    "/static/css/layout.css",
    "/static/css/components.css",
    "/static/css/footer.css",
    "/static/js/theme-toggle.js",
    "/static/js/favorite.js",
];

/* Установка: кэшируем статические ресурсы */
self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

/* Активация: удаляем старые кэши */
self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((names) =>
            Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
        )
    );
    self.clients.claim();
});

/* Fetch: стратегия зависит от типа запроса */
self.addEventListener("fetch", (event) => {
    const { request } = event;
    const url = new URL(request.url);

    /* API — Network Only */
    if (url.pathname.startsWith("/api/")) return;

    /* Статика — Cache First */
    if (url.pathname.startsWith("/static/")) {
        event.respondWith(
            caches.match(request).then((cached) => cached || fetch(request))
        );
        return;
    }

    /* Страницы — Network First */
    event.respondWith(
        fetch(request)
            .then((response) => {
                const clone = response.clone();
                caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
                return response;
            })
            .catch(() => caches.match(request))
    );
});
