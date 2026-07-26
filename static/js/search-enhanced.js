/*
  Улучшенный поиск: debounce + autocomplete + история + fuzzy.

  Debounce: не отправляем запрос на каждое нажатие клавиши,
  а ждём 300мс после последнего нажатия.

  Autocomplete: показываем подсказки из API при вводе ≥2 символов.

  История поиска: сохраняем последние 5 запросов в localStorage
  и показываем их при фокусе на пустом поле.

  Fuzzy: если мало результатов — показываем предложения по исправлению.
*/
(() => {
    const searchInput = document.getElementById("search-input");
    if (!searchInput) return;

    const STORAGE_KEY = "moviehub-search-history";
    const MAX_HISTORY = 5;
    const DEBOUNCE_MS = 300;
    const API_URL = "/api/v1/search/autocomplete/";

    /* ---------- История поиска ---------- */

    const getHistory = () => {
        try {
            return JSON.parse(localStorage.getItem(STORAGE_KEY)) || [];
        } catch {
            return [];
        }
    };

    const addToHistory = (query) => {
        if (!query.trim()) return;
        const history = getHistory().filter((item) => item !== query);
        history.unshift(query);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(0, MAX_HISTORY)));
    };

    /* ---------- Dropdown ---------- */

    let dropdown = null;

    const getOrCreateDropdown = () => {
        if (dropdown) return dropdown;
        dropdown = document.createElement("div");
        dropdown.className = "search-dropdown";
        dropdown.setAttribute("role", "listbox");
        searchInput.parentElement.appendChild(dropdown);
        return dropdown;
    };

    const hideDropdown = () => {
        if (dropdown) dropdown.hidden = true;
    };

    const showHistory = () => {
        const history = getHistory();
        if (!history.length) return;
        const dd = getOrCreateDropdown();
        dd.innerHTML = history
            .map((q) => `<button class="search-dropdown__item" type="button" role="option" data-query="${q}">🕐 ${q}</button>`)
            .join("");
        dd.hidden = false;
    };

    const showAutocomplete = (suggestions, corrections = []) => {
        const dd = getOrCreateDropdown();
        let html = "";

        /* Основные результаты */
        if (suggestions.length) {
            html += suggestions
                .map((s) => {
                    const type = s.type === "movie" ? "🎬" : "📺";
                    return `<a class="search-dropdown__item search-dropdown__link" href="${s.url}" role="option">${type} ${s.name} <small style="color:var(--color-text-dim);margin-left:auto">${s.year}</small></a>`;
                })
                .join("");
        }

        /* Предложения по исправлению */
        if (corrections.length) {
            html += `<div class="search-dropdown__divider" style="padding:4px 12px;color:var(--color-text-dim);font-size:0.75rem;border-top:1px solid var(--color-border);margin-top:4px;">Может быть, вы имели в виду:</div>`;
            html += corrections
                .map((c) => `<button class="search-dropdown__item" type="button" role="option" data-query="${c}">💡 ${c}</button>`)
                .join("");
        }

        if (!html) { hideDropdown(); return; }
        dd.innerHTML = html;
        dd.hidden = false;
    };

    /* ---------- Debounce ---------- */

    let debounceTimer = null;

    const debounce = (fn, ms) => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(fn, ms);
    };

    /* ---------- Autocomplete ---------- */

    const fetchAutocomplete = async (query) => {
        try {
            const response = await fetch(`${API_URL}?q=${encodeURIComponent(query)}`, {
                headers: { "Accept": "application/json" },
            });
            if (!response.ok) return;
            const data = await response.json();
            showAutocomplete(data.suggestions || [], data.corrections || []);
        } catch {
            /* Сеть недоступна — молча игнорируем */
        }
    };

    /* ---------- События ---------- */

    searchInput.addEventListener("focus", () => {
        if (!searchInput.value) showHistory();
    });

    searchInput.addEventListener("blur", () => {
        setTimeout(hideDropdown, 200);
    });

    searchInput.addEventListener("input", () => {
        const query = searchInput.value.trim();
        if (query.length >= 2) {
            debounce(() => fetchAutocomplete(query), DEBOUNCE_MS);
        } else if (query.length === 0) {
            showHistory();
        } else {
            hideDropdown();
        }
    });

    /* Клик по элементу истории */
    document.addEventListener("click", (event) => {
        const item = event.target.closest("[data-query]");
        if (!item) return;
        searchInput.value = item.dataset.query;
        hideDropdown();
        addToHistory(item.dataset.query);
        searchInput.closest("form").submit();
    });

    /* При отправке формы — сохраняем в историю */
    searchInput.closest("form").addEventListener("submit", () => {
        addToHistory(searchInput.value);
    });

    /* Закрываем dropdown при клике вне */
    document.addEventListener("click", (event) => {
        if (!event.target.closest(".search")) hideDropdown();
    });
})();
