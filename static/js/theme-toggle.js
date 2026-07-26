/*
  Переключатель темы (Dark / Light).

  Хранит выбор в localStorage.
  По умолчанию — тёмная тема, если нет сохранённого выбора
  и нет prefers-color-scheme: light.

  Работает без JS: тёмная тема — дефолтная в CSS.
*/
(() => {
    const STORAGE_KEY = "moviehub-theme";

    const getPreferred = () => {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) return saved;
        return window.matchMedia("(prefers-color-scheme: light)").matches
            ? "light"
            : "dark";
    };

    const apply = (theme) => {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem(STORAGE_KEY, theme);

        /* Обновляем иконку кнопки, если она есть */
        const btn = document.querySelector("[data-theme-toggle]");
        if (btn) {
            btn.textContent = theme === "light" ? "🌙" : "☀️";
            btn.setAttribute(
                "aria-label",
                theme === "light" ? "Switch to dark theme" : "Switch to light theme"
            );
        }
    };

    /* Применяем тему как можно раньше, чтобы не было вспышки */
    apply(getPreferred());

    /* Кнопка может появиться позже (defer), поэтому ждём DOMContentLoaded */
    document.addEventListener("DOMContentLoaded", () => {
        const btn = document.querySelector("[data-theme-toggle]");
        if (!btn) return;

        btn.addEventListener("click", () => {
            const current =
                document.documentElement.getAttribute("data-theme") || "dark";
            apply(current === "dark" ? "light" : "dark");
        });
    });
})();
