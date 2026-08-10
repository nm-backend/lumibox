/*
  Кнопки «В избранное» и «Смотреть позже» без перезагрузки страницы.

  Это улучшение, а не основа: формы отправляются обычным POST и работают
  с выключенным JavaScript. Скрипт лишь перехватывает отправку.
  Если он не загрузится, сайт останется полностью рабочим.

  Обе кнопки устроены одинаково, отличаются только ключом ответа —
  поэтому настройки собраны в один объект.

  Подписи и тексты уведомлений сюда не входят: они приходят из разметки
  через data-*. Раньше восемь русских строк были зашиты прямо здесь, и на
  английской с кыргызской версиями кнопка после нажатия отвечала
  по-русски — gettext до скрипта не достаёт.
*/

const BUTTON_KINDS = {
    favorite: {
        formSelector: "[data-favorite-form]",
        buttonSelector: "[data-favorite-button]",
        responseKey: "is_favorite",
    },
    watchlist: {
        formSelector: "[data-watchlist-form]",
        buttonSelector: "[data-watchlist-button]",
        responseKey: "is_watchlist",
    },
};

document.addEventListener("submit", async (event) => {
    const config = Object.values(BUTTON_KINDS).find((kind) =>
        event.target.closest(kind.formSelector)
    );
    if (!config) {
        return;
    }

    const form = event.target.closest(config.formSelector);
    const button = form.querySelector(config.buttonSelector);
    if (!button) {
        // Кнопка не нашлась (разметка изменилась) — отдаём отправку браузеру.
        return;
    }

    event.preventDefault();
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
        const isActive = Boolean(data[config.responseKey]);

        button.classList.toggle("button--active", isActive);

        // Подписи берём из разметки — там их перевёл шаблон.
        const label = button.querySelector("[data-button-label]");
        if (label) {
            const next = isActive ? form.dataset.labelOn : form.dataset.labelOff;
            if (next) label.textContent = next;
        }

        if (typeof window.showToast === 'function') {
            const toast = isActive ? form.dataset.toastOn : form.dataset.toastOff;
            if (toast) window.showToast(toast, isActive ? 'success' : 'info');
        }
    } catch {
        // Что-то пошло не так — отправляем форму обычным способом.
        // Пользователь получит результат, просто с перезагрузкой.
        form.submit();
    } finally {
        button.disabled = false;
    }
});
