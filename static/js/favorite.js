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

  Состояние кнопки меняется после ответа сервера, а не по нажатию: пока
  сервер не подтвердил сохранение, показывать «в избранном» нельзя.
*/

const BUTTON_KINDS = {
    favorite: {
        formSelector: "[data-favorite-form]",
        buttonSelector: "[data-favorite-button]",
        responseKey: "is_favorite",
        // Заполненный вариант есть только у сердца. Для закладки оба
        // состояния — один и тот же символ: выбранное показывает класс
        // button--active (акцентная обводка и заливка), а не подмена иконки.
        iconOn: "heart-filled",
        iconOff: "heart",
    },
    watchlist: {
        formSelector: "[data-watchlist-form]",
        buttonSelector: "[data-watchlist-button]",
        responseKey: "is_watchlist",
        iconOn: "bookmark",
        iconOff: "bookmark",
    },
};

/*
  Подменяет символ иконки внутри кнопки.

  Адрес спрайта берём из уже отрисованного <use>: в нём есть версия
  (?v=...), и собирать строку заново здесь значило бы продублировать
  логику версионирования из templatetag. Меняем только фрагмент.
*/
function swapIcon(button, name) {
    const use = button.querySelector("svg use");
    if (!use) {
        return;
    }

    const href = use.getAttribute("href") || use.getAttribute("xlink:href");
    if (!href) {
        return;
    }

    const next = href.replace(/#icon-[^#]+$/, `#icon-${name}`);
    if (next === href) {
        return;
    }

    use.setAttribute("href", next);
    if (use.hasAttribute("xlink:href")) {
        use.setAttribute("xlink:href", next);
    }
}

/*
  Синхронизирует подписи кнопки с её состоянием.

  aria-label читает скринридер, title — подсказку при наведении мышью.
  Раньше обновлялся только спрятанный <span>, а атрибуты оставались
  от первой отрисовки: после нажатия незрячий пользователь слышал
  прежнюю подпись, а наведение показывало прежний текст.
*/
function setLabels(button, form, isActive) {
    const next = isActive ? form.dataset.labelOn : form.dataset.labelOff;
    if (!next) {
        return;
    }

    button.setAttribute("aria-label", next);
    button.setAttribute("title", next);

    // Видимая подпись есть не у всех кнопок: у круглых иконок в карточке
    // её нет вовсе. Если она есть — обновляем и её.
    const visible = button.querySelector("[data-button-label]");
    if (visible) {
        visible.textContent = next;
    }
}

function notify(message, type) {
    if (message && typeof window.showToast === "function") {
        window.showToast(message, type);
    }
}

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

    // Гостю POST не имеет смысла: сервер ответит редиректом на /login/,
    // и посетитель уедет со страницы, хотя нажал всего одну кнопку.
    // Говорим об этом прямо и остаёмся на месте.
    if (form.dataset.loginRequired) {
        event.preventDefault();
        notify(form.dataset.loginRequired, "info");
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
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        const isActive = Boolean(data[config.responseKey]);

        button.classList.toggle("button--active", isActive);
        swapIcon(button, isActive ? config.iconOn : config.iconOff);
        setLabels(button, form, isActive);
        notify(isActive ? form.dataset.toastOn : form.dataset.toastOff, isActive ? "success" : "info");
    } catch {
        // Состояние не трогаем: показать «сохранено», когда сервер отказал,
        // хуже всего. И не отправляем форму сами — обычная отправка уходит
        // со страницы (гостя уводит на вход, вошедшего перезагружает),
        // а пользователь нажал одну кнопку. Честнее сказать об ошибке.
        notify(form.dataset.toastError, "error");
    } finally {
        button.disabled = false;
    }
});
