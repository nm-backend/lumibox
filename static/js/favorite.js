/*
  Кнопка «В избранное» без перезагрузки страницы.

  Это улучшение, а не основа: форма отправляется обычным POST и работает
  с выключенным JavaScript. Скрипт лишь перехватывает отправку.
  Если он не загрузится, сайт останется полностью рабочим.
*/

document.addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-favorite-form]");
    if (!form) {
        return;
    }

    event.preventDefault();

    const button = form.querySelector("[data-favorite-button]");
    button.disabled = true;

    try {
        const response = await fetch(form.action, {
            method: "POST",
            body: new FormData(form),
            headers: {
                // По этому заголовку сервер понимает, что ответить надо JSON,
                // а не редиректом.
                "X-Requested-With": "XMLHttpRequest",
            },
        });

        if (!response.ok) {
            throw new Error("Запрос не удался");
        }

        const data = await response.json();
        button.textContent = data.is_favorite ? "❤️ В избранном" : "🤍 В избранное";
        button.classList.toggle("button--active", data.is_favorite);

        // Toast notification
        if (typeof window.showToast === 'function') {
            window.showToast(
                data.is_favorite ? 'Добавлено в избранное' : 'Убрано из избранного',
                data.is_favorite ? 'success' : 'info'
            );
        }
    } catch {
        // Что-то пошло не так — отправляем форму обычным способом.
        // Пользователь получит результат, просто с перезагрузкой.
        form.submit();
    } finally {
        button.disabled = false;
    }
});
