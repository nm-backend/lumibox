/*
  WebSocket уведомления и real-time синхронизация контента.

  Подключается к ws://host/ws/notifications/ при загрузке страницы.
  Обрабатывает два типа сообщений:
  1. notification — персональные уведомления
  2. content_update — broadcast обновлений контента (новые фильмы, изменения)

  При content_update показывает toast с кнопкой "Обновить".
  Автоматически переподключается при обрыве соединения.
*/
(() => {
    /* Не запускаем для неавторизованных */
    const userId = document.querySelector("[data-user-id]");
    if (!userId) return;

    const RECONNECT_DELAY = 5000;
    const TOAST_DURATION = 8000;
    let ws = null;
    let reconnectTimer = null;

    /* Тексты событий для разных типов контента */
    const EVENT_LABELS = {
        new_content: "🎬 Новый фильм",
        content_updated: "✏️ Фильм обновлён",
        content_deleted: "🗑️ Фильм удалён",
        new_episode: "📺 Новая серия",
    };

    const connect = () => {
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        const url = `${protocol}//${location.host}/ws/notifications/`;

        try {
            ws = new WebSocket(url);
        } catch {
            return;
        }

        ws.onopen = () => {
            clearTimeout(reconnectTimer);
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                if (data.type === "notification") {
                    showToast(data.title, data.message, data.url);
                } else if (data.type === "content_update") {
                    handleContentUpdate(data);
                }
            } catch {
                /* Игнорируем некорректные сообщения */
            }
        };

        ws.onclose = () => {
            reconnectTimer = setTimeout(connect, RECONNECT_DELAY);
        };

        ws.onerror = () => {
            ws.close();
        };
    };

    const handleContentUpdate = (data) => {
        const label = EVENT_LABELS[data.event] || "📢 Обновление";
        const message = data.title || "Каталог обновлён";

        /* Показываем toast с кнопкой "Обновить" */
        showToast(label, message, data.url, true);
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

        /* Анимация появления */
        requestAnimationFrame(() => toast.classList.add("toast--visible"));

        /* Автоскрытие */
        setTimeout(() => {
            toast.classList.remove("toast--visible");
            setTimeout(() => toast.remove(), 300);
        }, TOAST_DURATION);
    };

    connect();
})();
