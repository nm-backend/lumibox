/*
  WebSocket уведомления, real-time синхронизация контента
  и Web Push подписка.

  1. WebSocket: подключается к ws://host/ws/notifications/
  2. Push API: подписывается на push-уведомления через Service Worker
*/
(() => {
    const userId = document.querySelector("[data-user-id]");
    if (!userId) return;

    const RECONNECT_DELAY = 5000;
    const TOAST_DURATION = 8000;
    let ws = null;
    let reconnectTimer = null;

    const EVENT_LABELS = {
        new_content: "🎬 Новый фильм",
        content_updated: "✏️ Фильм обновлён",
        content_deleted: "🗑️ Фильм удалён",
        new_episode: "📺 Новая серия",
    };

    /* ---- WebSocket ---- */
    const connect = () => {
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        const url = `${protocol}//${location.host}/ws/notifications/`;

        try {
            ws = new WebSocket(url);
        } catch { return; }

        ws.onopen = () => clearTimeout(reconnectTimer);

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === "notification") {
                    showToast(data.title, data.message, data.url);
                } else if (data.type === "content_update") {
                    handleContentUpdate(data);
                }
            } catch { /* Игнорируем некорректные сообщения */ }
        };

        ws.onclose = () => {
            reconnectTimer = setTimeout(connect, RECONNECT_DELAY);
        };
        ws.onerror = () => ws.close();
    };

    const handleContentUpdate = (data) => {
        const label = EVENT_LABELS[data.event] || "📢 Обновление";
        showToast(label, data.title || "Каталог обновлён", data.url, true);
    };

    const showToast = (title, message, url, showRefresh = false) => {
        const toast = document.createElement("div");
        toast.className = "toast";

        let actions = "";
        if (showRefresh) {
            actions = `<button class="toast__action toast__refresh" onclick="location.reload()">Обновить</button>`;
        }
        if (url) {
            actions += `<a class="toast__action" href="${url}">Открыть</a>`;
        }

        toast.innerHTML = `
            <div class="toast__content">
                <strong class="toast__title">${title}</strong>
                <p class="toast__message">${message}</p>
            </div>
            ${actions}
        `;

        document.body.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add("toast--visible"));

        setTimeout(() => {
            toast.classList.remove("toast--visible");
            setTimeout(() => toast.remove(), 300);
        }, TOAST_DURATION);
    };

    /* ---- Web Push подписка ---- */
    const subscribePush = async () => {
        if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;

        try {
            const reg = await navigator.serviceWorker.ready;

            // Проверяем, есть ли уже подписка
            const existing = await reg.pushManager.getSubscription();
            if (existing) return;

            // Получаем VAPID публичный ключ
            const resp = await fetch("/api/v1/push/vapid-key/");
            if (!resp.ok) return;
            const { vapid_public_key } = await resp.json();
            if (!vapid_public_key) return;

            // Конвертируем base64 в Uint8Array
            const key = urlBase64ToUint8Array(vapid_public_key);

            // Подписываемся
            const subscription = await reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: key,
            });

            // Отправляем подписку на сервер
            await fetch("/api/v1/push/subscribe/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken(),
                },
                body: JSON.stringify({ subscription: subscription.toJSON() }),
            });
        } catch {
            /* Push подписка не критична — не блокируем страницу */
        }
    };

    const urlBase64ToUint8Array = (base64String) => {
        const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
        const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
        const rawData = atob(base64);
        return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
    };

    const getCsrfToken = () => {
        const cookie = document.cookie.split(";").find((c) => c.trim().startsWith("csrftoken="));
        return cookie ? cookie.split("=")[1] : "";
    };

    connect();
    subscribePush();
})();
