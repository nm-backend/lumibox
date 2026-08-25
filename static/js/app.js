/* Main LumiBox application JS */

(function () {
    'use strict';

    /* Подписи для элементов, которые скрипт создаёт сам (тост, кнопка
       «наверх»). Строки лежат на <body> в data-ui-*: перевод делает шаблон,
       а gettext до скрипта не достаёт. Пустая строка вместо русского
       текста по умолчанию — чтобы забытая подпись была видна на проверке
       доступности, а не притворялась переводом. */
    function uiLabel(name) {
        return document.body.dataset['ui' + name.charAt(0).toUpperCase() + name.slice(1)] || '';
    }

    /* Прокрутка с оглядкой на настройку системы.

       В CSS отказ от анимаций учитывался (scroll-behavior: auto), но
       программная прокрутка с behavior: 'smooth' это правило игнорирует —
       опция в вызове сильнее. Человек, отключивший анимации из-за
       чувствительности к движению, всё равно получал плавный проезд
       через всю страницу по кнопке «наверх». */
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

    function scrollBehavior() {
        return reduceMotion.matches ? 'auto' : 'smooth';
    }

    /* -----------------------------------------------
       1. Theme toggle (dark/light)
    ----------------------------------------------- */
    const themeToggle = document.querySelector('[data-theme-toggle]');
    const html = document.documentElement;
    const stored = localStorage.getItem('lumibox-theme');
    /* Сравнение с null, а не проверка на «истинность»: тёмная тема хранится
       пустой строкой, и обычная проверка считала её «ничего не выбрано» —
       выбор тёмной не переживал перезагрузку. */
    if (stored !== null) html.dataset.theme = stored;
    if (themeToggle) {
        // Подписи приходят из разметки: gettext до скрипта не достаёт,
        // и зашитые здесь строки оставались русскими на en и ky.
        const setAriaLabel = () => {
            const label = html.dataset.theme === 'light'
                ? themeToggle.dataset.labelDark
                : themeToggle.dataset.labelLight;
            if (label) themeToggle.setAttribute('aria-label', label);
        };
        setAriaLabel();
        themeToggle.addEventListener('click', () => {
            html.dataset.theme = html.dataset.theme === 'light' ? '' : 'light';
            localStorage.setItem('lumibox-theme', html.dataset.theme);
            setAriaLabel();
        });
    }

    /* -----------------------------------------------
       2. Search autocomplete
    ----------------------------------------------- */
    const searchInput = document.querySelector('[data-search-input]');
    const dropdown = document.querySelector('[data-search-dropdown]');
    let searchTimer = null;
    // Отмена устаревшего запроса: без неё медленный ответ может прийти
    // после свежего и переписать подсказки результатами старого ввода.
    let searchController = null;

    if (searchInput && dropdown) {
        searchInput.addEventListener('input', function () {
            const q = this.value.trim();
            if (q.length < 2) {
                dropdown.classList.remove('search__dropdown--open');
                if (searchController) { searchController.abort(); searchController = null; }
                return;
            }
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => fetchSuggestions(q), 250);
        });

        document.addEventListener('click', function (e) {
            if (!e.target.closest('.search-wrapper')) {
                dropdown.classList.remove('search__dropdown--open');
            }
        });

        searchInput.addEventListener('focus', function () {
            if (this.value.trim().length >= 2) dropdown.classList.add('search__dropdown--open');
        });

        /* Подписи берём из разметки: перевод делает шаблон, а не скрипт.
           Тот же приём уже применён в поиске по актёрам. */
        function emptyMessage() {
            return dropdown.dataset.emptyMsg || '';
        }

        /* Клавиатура в подсказках. Без неё список открывался, но дойти
           до него можно было только мышью: стрелки просто двигали курсор
           внутри поля ввода. */
        searchInput.addEventListener('keydown', function (event) {
            const items = Array.from(dropdown.querySelectorAll('.search__suggestion'));
            if (!items.length || !dropdown.classList.contains('search__dropdown--open')) return;

            const current = items.indexOf(document.activeElement);
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                items[Math.min(current + 1, items.length - 1)].focus();
            } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                if (current <= 0) searchInput.focus();
                else items[current - 1].focus();
            } else if (event.key === 'Escape') {
                dropdown.classList.remove('search__dropdown--open');
            }
        });

        dropdown.addEventListener('keydown', function (event) {
            const items = Array.from(dropdown.querySelectorAll('.search__suggestion'));
            const current = items.indexOf(document.activeElement);
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                items[Math.min(current + 1, items.length - 1)].focus();
            } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                if (current <= 0) searchInput.focus();
                else items[current - 1].focus();
            } else if (event.key === 'Escape') {
                dropdown.classList.remove('search__dropdown--open');
                searchInput.focus();
            }
        });

        /* Заглушки на время запроса. Единственное место в проекте, где
           содержимое действительно приезжает после отрисовки страницы —
           и до этого правки оно молчало: на медленной сети список просто
           оставался пустым, и отличить «ищем» от «ничего нет» было нельзя. */
        function renderLoading() {
            dropdown.replaceChildren();
            for (let i = 0; i < 3; i++) {
                const row = element('div', 'search__suggestion search__suggestion--loading');
                row.appendChild(element('span', 'skeleton search__suggestion-poster'));
                const body = element('div', 'search__suggestion-body');
                body.appendChild(element('span', 'skeleton search__skeleton-line'));
                body.appendChild(element('span', 'skeleton search__skeleton-line search__skeleton-line--short'));
                row.appendChild(body);
                dropdown.appendChild(row);
            }
            dropdown.setAttribute('aria-busy', 'true');
            dropdown.classList.add('search__dropdown--open');
        }

        async function fetchSuggestions(q) {
            if (searchController) searchController.abort();
            const controller = new AbortController();
            searchController = controller;
            renderLoading();
            try {
                const response = await fetch(`/api/v1/titles/search/?q=${encodeURIComponent(q)}&limit=6`, {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                    signal: controller.signal
                });
                if (!response.ok) throw new Error('Search failed');
                const data = await response.json();
                if (controller.signal.aborted) return;
                renderSuggestions(data.results || data);
            } catch (error) {
                if (error && error.name === 'AbortError') return;
                /* Ошибку сети показываем словами. Раньше список молча
                   закрывался, и это выглядело как «ничего не найдено» —
                   человек делал вывод, что фильма на сайте нет. */
                dropdown.replaceChildren();
                dropdown.appendChild(element('div', 'search__no-results', dropdown.dataset.errorMsg || ''));
                dropdown.classList.add('search__dropdown--open');
            } finally {
                dropdown.removeAttribute('aria-busy');
                if (searchController === controller) searchController = null;
            }
        }

        /* Подсказки собираем узлами DOM, а не строкой в innerHTML.
           Название фильма приходит из базы: пока его вставляли в шаблонную
           строку, редактор мог сохранить фильм с именем вида
           <img src=x onerror=...> — и этот код выполнялся бы в браузере
           каждого, кто просто набирает запрос в поиске.
           textContent подставляет текст текстом, что бы в нём ни лежало. */
        function element(tag, className, text) {
            const node = document.createElement(tag);
            node.className = className;
            if (text !== undefined && text !== null) node.textContent = text;
            return node;
        }

        function renderSuggestions(items) {
            dropdown.removeAttribute('aria-busy');
            dropdown.replaceChildren();
            if (!items || items.length === 0) {
                dropdown.appendChild(element('div', 'search__no-results', emptyMessage()));
                dropdown.classList.add('search__dropdown--open');
                return;
            }
            const list = document.createElement('div');
            items.forEach(item => {
                const name = item.name || '';
                const link = document.createElement('a');
                link.className = 'search__suggestion';
                link.href = item.url || `/title/${encodeURIComponent(item.slug || '')}/`;

                if (item.type === 'person') {
                    if (item.poster) {
                        const photo = element('img', 'search__suggestion-photo');
                        photo.src = item.poster;
                        photo.alt = '';
                        photo.loading = 'lazy';
                        link.appendChild(photo);
                    } else {
                        link.appendChild(
                            element('span', 'search__suggestion-photo--placeholder', (name || '?')[0])
                        );
                    }
                } else {
                    if (item.poster) {
                        const poster = element('img', 'search__suggestion-poster');
                        poster.src = item.poster;
                        poster.alt = '';
                        poster.loading = 'lazy';
                        link.appendChild(poster);
                    } else {
                        link.appendChild(
                            element('span', 'search__suggestion-poster-placeholder', (name || '?')[0])
                        );
                    }
                }

                const body = element('span', 'search__suggestion-body');
                body.appendChild(element('span', 'search__suggestion-name', name));

                /* Подпись типа приходит с сервера (type_display). Раньше
                   скрипт решал сам: всё, что не «movie», подписывалось
                   «Сериал» — мультфильмы и ТВ-шоу выглядели сериалами,
                   и перевести это было негде. */
                const meta = [item.release_year || '', item.type_display || '']
                    .filter(Boolean)
                    .join(' · ');
                body.appendChild(element('span', 'search__suggestion-meta', meta));

                link.appendChild(body);
                list.appendChild(link);
            });
            dropdown.appendChild(list);
            dropdown.classList.add('search__dropdown--open');
        }
    }

    /* -----------------------------------------------
       3. Carousel (horizontal scroll)
    ----------------------------------------------- */
    document.querySelectorAll('.carousel').forEach(function (carousel) {
        const track = carousel.querySelector('.carousel__track');
        const prevBtn = carousel.querySelector('.carousel__btn--prev');
        const nextBtn = carousel.querySelector('.carousel__btn--next');
        if (!track) return;

        const scrollAmount = () => {
            const first = track.children[0];
            if (!first) return 300;
            return first.offsetWidth + parseInt(getComputedStyle(track).gap || '16');
        };

        const updateButtons = () => {
            if (prevBtn) prevBtn.style.display = track.scrollLeft <= 0 ? 'none' : '';
            if (nextBtn) {
                const maxScroll = track.scrollWidth - track.clientWidth;
                nextBtn.style.display = track.scrollLeft >= maxScroll - 5 ? 'none' : '';
            }
        };

        if (prevBtn) {
            prevBtn.addEventListener('click', function () {
                track.scrollBy({ left: -scrollAmount(), behavior: scrollBehavior() });
                updateButtons();
            });
        }
        if (nextBtn) {
            nextBtn.addEventListener('click', function () {
                track.scrollBy({ left: scrollAmount(), behavior: scrollBehavior() });
                updateButtons();
            });
        }
        if ('onscrollend' in window) {
            track.addEventListener('scrollend', updateButtons);
        }
        updateButtons();
    });

    /* -----------------------------------------------
       4. Hamburger / Mobile nav
    ----------------------------------------------- */
    const hamburger = document.querySelector('[data-hamburger]');
    const mobileNav = document.querySelector('[data-mobile-nav]');
    if (hamburger && mobileNav) {
        /* Меню занимает весь экран под шапкой, то есть ведёт себя как диалог.
           Раньше оно только меняло класс: фон под ним продолжал прокручиваться
           (палец «проваливался» в страницу), Esc не закрывал, фокус оставался
           на странице позади, а вернуться к гамбургеру с клавиатуры было
           нельзя. Дальше — минимальный набор, который делает его диалогом. */
        const setOpen = function (open) {
            if (open) {
                /* Низ шапки — фактический, а не из переменной: над шапкой есть
                   промо-полоса, которая уезжает при прокрутке, поэтому одно
                   зашитое число всегда было бы неверным на половине экранов. */
                const header = document.querySelector('.site-header');
                if (header) {
                    const bottom = Math.max(0, Math.round(header.getBoundingClientRect().bottom));
                    document.documentElement.style.setProperty('--lb-drawer-top', bottom + 'px');
                }
            }
            mobileNav.classList.toggle('mobile-nav--open', open);
            hamburger.classList.toggle('hamburger--active', open);
            hamburger.setAttribute('aria-expanded', open ? 'true' : 'false');
            /* Прокрутку блокируем на <html>: на iOS overflow:hidden у body
               не удерживает страницу, а класс на корне переживает и смену
               темы, и перерисовку. */
            document.documentElement.classList.toggle('nav-open', open);
            if (open) {
                const first = mobileNav.querySelector('a, button');
                if (first) first.focus();
            }
        };

        const isOpen = function () {
            return mobileNav.classList.contains('mobile-nav--open');
        };

        hamburger.addEventListener('click', function () {
            setOpen(!isOpen());
        });

        mobileNav.querySelectorAll('a').forEach(function (link) {
            link.addEventListener('click', function () {
                setOpen(false);
            });
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && isOpen()) {
                setOpen(false);
                hamburger.focus();
            }
        });

        /* Тап мимо меню — привычный способ его закрыть. Гамбургер исключаем:
           его собственный обработчик уже переключает состояние, иначе меню
           закрылось бы и тут же открылось снова. */
        document.addEventListener('click', function (event) {
            if (!isOpen()) return;
            if (mobileNav.contains(event.target) || hamburger.contains(event.target)) return;
            setOpen(false);
        });

        /* Поворот телефона или переход на планшетную ширину: если гамбургер
           уехал из вёрстки, открытое меню осталось бы висеть поверх страницы
           без кнопки закрытия. */
        window.addEventListener('resize', function () {
            if (isOpen() && getComputedStyle(hamburger).display === 'none') setOpen(false);
        });
    }

    /* -----------------------------------------------
       4b. Мобильный поиск (кнопка-лупа)
    ----------------------------------------------- */
    const searchToggle = document.querySelector('[data-search-toggle]');
    const searchInputEl = document.querySelector('[data-search-input]');
    if (searchToggle) {
        const setSearchOpen = function (open) {
            document.documentElement.classList.toggle('search-open', open);
            searchToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
            if (open && searchInputEl) {
                // Поле только что появилось в DOM — фокус после кадра.
                requestAnimationFrame(function () { searchInputEl.focus(); });
            }
        };

        searchToggle.addEventListener('click', function () {
            const isOpen = document.documentElement.classList.contains('search-open');
            setSearchOpen(!isOpen);
        });

        // Esc закрывает раскрытый поиск.
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && document.documentElement.classList.contains('search-open')) {
                setSearchOpen(false);
                searchToggle.focus();
            }
        });
    }

    /* -----------------------------------------------
       5. Lightbox
    ----------------------------------------------- */
    const lightbox = document.querySelector('[data-lightbox]');
    const lightboxImg = document.querySelector('[data-lightbox-img]');
    const lightboxClose = document.querySelector('[data-lightbox-close]');

    if (lightbox && lightboxImg && lightboxClose) {
        /* Лайтбокс — диалог, и вести себя должен как диалог. Раньше он только
           показывался: фокус оставался на странице позади, Tab уходил в
           содержимое под ним, а после закрытия возвращаться было некуда.
           Обработчик Esc при этом висел всегда и на каждое нажатие сбрасывал
           overflow у body — конфликтуя с модалкой трейлера на той же странице. */
        let lightboxOpener = null;

        const isLightboxOpen = function () {
            return lightbox.classList.contains('lightbox--open');
        };

        document.querySelectorAll('[data-lightbox-trigger]').forEach(function (trigger) {
            trigger.addEventListener('click', function () {
                const src = this.dataset.lightboxTrigger || this.src;
                lightboxOpener = this;
                lightboxImg.src = src;
                lightbox.classList.add('lightbox--open');
                document.body.style.overflow = 'hidden';
                lightboxClose.focus();
            });
        });

        const closeLightbox = function () {
            if (!isLightboxOpen()) return;
            lightbox.classList.remove('lightbox--open');
            document.body.style.overflow = '';
            lightboxImg.removeAttribute('src');
            /* Возвращаем фокус на тот кадр, с которого открыли: иначе
               обход продолжится с начала страницы. */
            if (lightboxOpener) lightboxOpener.focus();
            lightboxOpener = null;
        };

        lightboxClose.addEventListener('click', closeLightbox);
        lightbox.addEventListener('click', function (e) {
            if (e.target === lightbox) closeLightbox();
        });
        document.addEventListener('keydown', function (e) {
            if (!isLightboxOpen()) return;
            if (e.key === 'Escape') {
                closeLightbox();
                return;
            }
            /* Внутри открытого диалога фокусируемый элемент один — кнопка
               закрытия, поэтому ловушка сводится к тому, чтобы Tab не уводил
               наружу. */
            if (e.key === 'Tab') {
                e.preventDefault();
                lightboxClose.focus();
            }
        });
    }

    /* -----------------------------------------------
        5b. Confirm on destructive forms
        Форма с data-confirm спрашивает перед отправкой.
        Текст подтверждения задан в шаблоне (i18n).
    ----------------------------------------------- */
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
        form.addEventListener('submit', function (event) {
            if (!window.confirm(form.dataset.confirm)) {
                event.preventDefault();
            }
        });
    });

    /* -----------------------------------------------
        6. Tabs
    ----------------------------------------------- */
    document.querySelectorAll('[data-tabs]').forEach(function (container) {
        // Контент вкладок лежит рядом с контейнером, а не внутри него:
        // в шаблонах это соседние <div class="tab-content">. Ищем в родителе.
        const scope = container.parentElement || document;
        const tabs = Array.from(scope.querySelectorAll('[data-tab]'));
        const contents = scope.querySelectorAll('[data-tab-content]');
        if (!tabs.length) return;

        /* Роли и клавиатура. У вкладок плеера всё это было, а у контентных —
           нет: скринридер объявлял их обычными кнопками, а стрелки не
           работали. Проставляем здесь, чтобы шаблоны не дублировали
           одни и те же атрибуты на каждой вкладке. */
        container.setAttribute('role', 'tablist');

        function select(tab, moveFocus) {
            tabs.forEach(function (item) {
                const isActive = item === tab;
                item.classList.toggle('tab--active', isActive);
                item.setAttribute('role', 'tab');
                item.setAttribute('aria-selected', String(isActive));
                item.tabIndex = isActive ? 0 : -1;
            });
            contents.forEach(function (content) {
                const isActive = content.dataset.tabContent === tab.dataset.tab;
                content.classList.toggle('tab-content--active', isActive);
                content.setAttribute('role', 'tabpanel');
                /* hidden, а не только класс: пока панель пряталась одним
                   оформлением, её содержимое оставалось в дереве доступности
                   и в порядке обхода Tab. Скринридер читал отзывы, создателей
                   и комментарии подряд как сплошной текст, а клавиша Tab
                   уходила в невидимые ссылки. */
                content.hidden = !isActive;
                /* Панель должна принимать фокус: со вкладки стрелками
                   переходят к её содержимому. */
                content.tabIndex = isActive ? 0 : -1;
                if (isActive) {
                    content.setAttribute('aria-labelledby', tab.id || '');
                }
            });
            if (moveFocus) tab.focus();
        }

        tabs.forEach(function (tab, index) {
            /* id нужен, чтобы панель могла сослаться на свою вкладку через
               aria-labelledby: иначе скринридер объявляет панель без имени. */
            if (!tab.id) tab.id = 'tab-' + (tab.dataset.tab || index);
            tab.addEventListener('click', function () {
                select(tab, false);
            });
            tab.addEventListener('keydown', function (event) {
                let next = null;
                if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
                else if (event.key === 'ArrowLeft') next = tabs[(index - 1 + tabs.length) % tabs.length];
                else if (event.key === 'Home') next = tabs[0];
                else if (event.key === 'End') next = tabs[tabs.length - 1];
                if (!next) return;
                event.preventDefault();
                select(next, true);
            });
        });

        select(tabs.find(t => t.classList.contains('tab--active')) || tabs[0], false);
    });

    /* -----------------------------------------------
       7. Trailer autoplay on hover (hero)
    ----------------------------------------------- */
    const heroVideo = document.querySelector('[data-hero-video]');
    if (heroVideo) {
        heroVideo.addEventListener('mouseenter', function () {
            this.play().catch(() => {});
        });
        heroVideo.addEventListener('mouseleave', function () {
            this.pause();
        });
    }

    /* -----------------------------------------------
        8. Toast notifications
    ----------------------------------------------- */
    const toastContainer = document.querySelector('[data-toast-container]');
    if (!toastContainer) {
        const container = document.createElement('div');
        container.className = 'toast-container';
        container.setAttribute('data-toast-container', '');
        document.body.appendChild(container);
    }

    /* Иконки для тостов — inline SVG, чтобы не зависеть от спрайта
       в динамически создаваемом контенте. */
    const TOAST_ICONS = {
        success: '<svg class="toast__icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
        error: '<svg class="toast__icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
        info: '<svg class="toast__icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    };
    const TOAST_CLOSE_ICON = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

    /* Разбираем статичную SVG-строку иконки в DOM-узел: строка своя,
       константа, поэтому её можно скормить template.innerHTML.
       А вот message пользовательский текст — его вставляем только
       через textContent, чтобы название фильма из базы не исполнилось
       как разметка. */
    const svgFromString = function (html) {
        const template = document.createElement('template');
        template.innerHTML = html.trim();
        return template.content.firstElementChild;
    };

    window.showToast = function (message, type = 'info', duration = 4000) {
        const container = document.querySelector('[data-toast-container]');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast toast--${type}`;
        toast.appendChild(svgFromString(TOAST_ICONS[type] || TOAST_ICONS.info));

        const messageEl = document.createElement('span');
        messageEl.className = 'toast__message';
        messageEl.textContent = message;
        toast.appendChild(messageEl);

        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'toast__close';
        closeBtn.setAttribute('aria-label', uiLabel('close'));
        closeBtn.appendChild(svgFromString(TOAST_CLOSE_ICON));
        closeBtn.addEventListener('click', () => {
            toast.style.animation = 'toastOut 0.25s ease both';
            setTimeout(() => toast.remove(), 300);
        });
        toast.appendChild(closeBtn);

        container.appendChild(toast);

        if (duration > 0) {
            setTimeout(() => {
                if (toast.isConnected) {
                    toast.style.animation = 'toastOut 0.25s ease both';
                    setTimeout(() => toast.remove(), 300);
                }
            }, duration);
        }
    };

    /* -----------------------------------------------
        9. Unified scroll handler
    ----------------------------------------------- */
    const header = document.querySelector('.site-header');
    const topnavBar = document.querySelector('.lb-topnav-bar');
    let isScrolled = false;
    const scrollBtn = document.querySelector('[data-scroll-top]');
    if (!scrollBtn) {
        const btn = document.createElement('button');
        btn.className = 'scroll-top';
        btn.setAttribute('data-scroll-top', '');
        btn.setAttribute('aria-label', uiLabel('scrollTop'));
        btn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"/></svg>';
        document.body.appendChild(btn);
        btn.addEventListener('click', () => {
            window.scrollTo({ top: 0, behavior: scrollBehavior() });
        });
    }

    let scrollVisible = false;
    window.addEventListener('scroll', () => {
        const y = window.scrollY;

        // Header shadow
        if (header) {
            const shouldScroll = y > 10;
            if (shouldScroll !== isScrolled) {
                header.classList.toggle('site-header--scrolled', shouldScroll);
                /* Топнав — стеклянная полоса: в спокойном состоянии она
                   полупрозрачна, но при прокрутке сквозь неё просвечивает
                   контент (заголовок фильма). Становится непрозрачной
                   ровно вместе с шапкой, от того же порога. */
                if (topnavBar) topnavBar.classList.toggle('lb-topnav-bar--scrolled', shouldScroll);
                isScrolled = shouldScroll;
            }
        }

        // Scroll-to-top button
        const shouldShow = y > 400;
        if (shouldShow !== scrollVisible) {
            const st = document.querySelector('[data-scroll-top]');
            if (st) { st.classList.toggle('scroll-top--visible', shouldShow); }
            scrollVisible = shouldShow;
        }
    }, { passive: true });

    /* -----------------------------------------------
       10. Touch swipe for carousels
    ----------------------------------------------- */
    document.querySelectorAll('.carousel__track').forEach(function (track) {
        let startX = 0;
        let startScrollLeft = 0;
        let isSwiping = false;

        track.addEventListener('touchstart', function (e) {
            startX = e.touches[0].pageX;
            startScrollLeft = this.scrollLeft;
            isSwiping = true;
        }, { passive: true });

        track.addEventListener('touchmove', function (e) {
            if (!isSwiping) return;
            const deltaX = startX - e.touches[0].pageX;
            this.scrollLeft = startScrollLeft + deltaX;
        }, { passive: true });

        track.addEventListener('touchend', function () {
            isSwiping = false;
        }, { passive: true });
    });

    /* -----------------------------------------------
       14. Page entrance animation on load
    ----------------------------------------------- */
    const siteMain = document.querySelector('.site-main');
    if (siteMain) siteMain.classList.add('page-enter');

    /* Уплотнение шапки при прокрутке живёт в пункте 9 — там один общий
       обработчик scroll на всю страницу. Здесь раньше стоял его дубликат,
       принесённый слиянием: он повторно объявлял const header, из-за чего
       весь файл падал с SyntaxError и на сайте не работал ни один скрипт,
       и вешал второй слушатель прокрутки на то же самое действие. */

    /* -----------------------------------------------
       15. Button ripple effect
    ----------------------------------------------- */
    document.querySelectorAll('.button').forEach(function (btn) {
        btn.addEventListener('pointerdown', function (e) {
            const rect = this.getBoundingClientRect();
            this.style.setProperty('--ripple-x', ((e.clientX - rect.left) / rect.width * 100) + '%');
            this.style.setProperty('--ripple-y', ((e.clientY - rect.top) / rect.height * 100) + '%');
        });
    });

    /* -----------------------------------------------
       16. Keyboard shortcuts (global)
    ----------------------------------------------- */
    document.addEventListener('keydown', function (e) {
        // Целью может быть сам document (клавиша нажата без фокуса на элементе) —
        // у него нет .matches(), и вызов падал с TypeError. Проверяем заранее.
        if (!(e.target instanceof Element)) return;
        if (e.target.matches('input, select, textarea, [contenteditable]')) return;
        // / to focus search
        if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
            e.preventDefault();
            const input = document.querySelector('[data-search-input]');
            if (input) input.focus();
        }
    });

    /* -----------------------------------------------
       12. Card placeholder deterministic gradients
    ----------------------------------------------- */
    document.querySelectorAll('.card__placeholder').forEach(function(el) {
        var card = el.closest('.card');
        if (!card) return;
        var name = card.querySelector('.card__name');
        if (!name) return;
        var text = name.textContent || '';
        var hash = 0;
        for (var i = 0; i < text.length; i++) {
            hash = text.charCodeAt(i) + ((hash << 5) - hash);
        }
        var hue = Math.abs(hash % 360);
        el.style.setProperty('--card-hue', hue);
    });

    document.querySelectorAll('.collection-card__fallback').forEach(function(el) {
        var text = el.textContent || '';
        var hash = 0;
        for (var i = 0; i < text.length; i++) {
            hash = text.charCodeAt(i) + ((hash << 5) - hash);
        }
        var hue = Math.abs(hash % 360);
        el.style.setProperty('--card-hue', hue);
    });

    /* -----------------------------------------------
       13. Bottom-nav active link
    ----------------------------------------------- */
    {
        const nav = document.querySelector('.bottom-nav');
        if (nav) {
            const current = window.location.pathname;
            nav.querySelectorAll('.bottom-nav__link').forEach(function (link) {
                const href = link.getAttribute('href');
                if (href && href !== '#') {
                    const isHome = href === '/';
                    if ((isHome && current === '/') || (!isHome && current.startsWith(href))) {
                        link.classList.add('bottom-nav__link--active');
                    }
                }
            });
        }
    }

    /* -----------------------------------------------
       18. Blur-up image loading — mark images as loaded
       Triggers the CSS blurUp animation for progressive enhancement.
    ----------------------------------------------- */
    function markImageLoaded(img) {
        if (img.complete && img.naturalWidth > 0) {
            img.dataset.loaded = '';
        } else {
            img.addEventListener('load', function () {
                this.dataset.loaded = '';
            }, { once: true });
            img.addEventListener('error', function () {
                this.dataset.loaded = '';
                this.style.opacity = '0.3';
            }, { once: true });
        }
    }

    document.querySelectorAll('img').forEach(markImageLoaded);

    // Also observe dynamically added images (e.g. search suggestions)
    if ('MutationObserver' in window) {
        const imgObserver = new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                mutation.addedNodes.forEach(function (node) {
                    if (node.nodeName === 'IMG') {
                        markImageLoaded(node);
                    } else if (node.querySelectorAll) {
                        node.querySelectorAll('img').forEach(markImageLoaded);
                    }
                });
            });
        });
        imgObserver.observe(document.body, { childList: true, subtree: true });
    }

    /* -----------------------------------------------
       19. Отправка формы: состояние и защита от повтора

       Ни одна форма проекта не показывала, что отправка идёт, и не мешала
       нажать кнопку второй раз. Двойной клик по «Отправить» под комментарием
       создавал два одинаковых комментария, а на медленной сети человек не
       понимал, нажалась ли кнопка вообще.

       Делегируем на document: формы приходят и из шаблонов, и из
       перерисованной страницы с ошибками, и вешать обработчик на каждую
       по отдельности пришлось бы после каждой такой перерисовки.
    ----------------------------------------------- */
    document.addEventListener('submit', function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        /* Формы избранного шлёт favorite.js своим запросом и сам блокирует
           кнопку — второй блокировщик мешал бы ему вернуть её обратно. */
        if (form.hasAttribute('data-favorite-form') || form.hasAttribute('data-watchlist-form')) return;
        if (form.dataset.submitting === '1') {
            event.preventDefault();
            return;
        }
        form.dataset.submitting = '1';

        const button = form.querySelector('button[type="submit"], input[type="submit"]');
        if (!button) return;
        button.setAttribute('aria-busy', 'true');
        button.classList.add('is-loading');
        /* disabled ставим после кадра: браузер не отправляет значение
           отключённой кнопки, и форма потеряла бы имя нажатой кнопки. */
        requestAnimationFrame(function () {
            button.disabled = true;
        });
    });

    /* Возврат по кнопке «назад» отдаёт страницу из кэша вместе с состоянием
       DOM: без сброса зритель увидел бы форму с навсегда заблокированной
       кнопкой. */
    window.addEventListener('pageshow', function (event) {
        if (!event.persisted) return;
        document.querySelectorAll('form[data-submitting="1"]').forEach(function (form) {
            form.dataset.submitting = '';
            const button = form.querySelector('button[type="submit"], input[type="submit"]');
            if (!button) return;
            button.disabled = false;
            button.removeAttribute('aria-busy');
            button.classList.remove('is-loading');
        });
    });

})();
