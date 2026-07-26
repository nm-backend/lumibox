/*
  Service Worker для MovieHub PWA.

  Кэширует статические ресурсы (CSS, JS, изображения)
  для офлайн-доступа и ускорения загрузки.

  Стратегия:
  - Статика: Cache First (из кэша, потом из сети)
  - Изображения: Cache First с лимитом (50 штук)
  - Страницы: Network First (из сети, потом из кэша)
  - API: Network Only (всегда из сети)
*/

const CACHE_NAME = "moviehub-v2";
const IMAGE_CACHE = "moviehub-images-v1";
const MAX_IMAGES = 50;
const STATIC_ASSETS = [
    "/static/css/variables.css",
    "/static/css/base.css",
    "/static/css/layout.css",
    "/static/css/components.css",
    "/static/css/footer.css",
    "/static/css/ads.css",
    "/static/js/theme-toggle.js",
    "/static/js/favorite.js",
    "/static/js/scroll-reveal.js",
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
            Promise.all(
                names
                    .filter((n) => n !== CACHE_NAME && n !== IMAGE_CACHE)
                    .map((n) => caches.delete(n))
            )
        )
    );
    self.clients.claim();
});

/* Очистка кэша изображений если превышен лимит */
async function trimImageCache() {
    const cache = await caches.open(IMAGE_CACHE);
    const keys = await cache.keys();
    if (keys.length > MAX_IMAGES) {
        await cache.delete(keys[0]);
        await trimImageCache();
    }
}

/* Fetch: стратегия зависит от типа запроса */
self.addEventListener("fetch", (event) => {
    const { request } = event;
    const url = new URL(request.url);

    /* API и аналитика — Network Only */
    if (url.pathname.startsWith("/api/")) return;
    if (url.hostname.includes("google-analytics.com")) return;
    if (url.hostname.includes("googletagmanager.com")) return;
    if (url.hostname.includes("mc.yandex.ru")) return;

    /* Статика — Cache First */
    if (url.pathname.startsWith("/static/")) {
        event.respondWith(
            caches.match(request).then((cached) => cached || fetch(request))
        );
        return;
    }

    /* Изображения — Cache First с лимитом */
    if (request.destination === "image" || url.pathname.startsWith("/media/")) {
        event.respondWith(
            caches.open(IMAGE_CACHE).then((cache) =>
                cache.match(request).then((cached) => {
                    if (cached) return cached;
                    return fetch(request).then((response) => {
                        if (response.ok) {
                            cache.put(request, response.clone());
                            trimImageCache();
                        }
                        return response;
                    });
                })
            )
        );
        return;
    }

    /* Страницы — Network First */
    if (request.mode === "navigate") {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
                    return response;
                })
                .catch(() =>
                    caches.match(request).then(
                        (cached) =>
                            cached ||
                            new Response(
                                "<!DOCTYPE html><html><body style='background:#0b0d12;color:#eef1f7;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0'><div style='text-align:center'><h1 style='font-size:3rem'>📡</h1><p>Нет соединения. Проверьте интернет.</p></div></body></html>",
                                { headers: { "Content-Type": "text/html; charset=utf-8" } }
                            )
                    )
                )
        );
        return;
    }
});
