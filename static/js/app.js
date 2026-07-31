/* Main LumiBox application JS */

(function () {
    'use strict';

    /* -----------------------------------------------
       1. Theme toggle (dark/light)
    ----------------------------------------------- */
    const themeToggle = document.querySelector('[data-theme-toggle]');
    const html = document.documentElement;
    const stored = localStorage.getItem('lumibox-theme');
    if (stored) html.dataset.theme = stored;
    if (themeToggle) {
        const setAriaLabel = () => {
            themeToggle.setAttribute('aria-label', html.dataset.theme === 'light' ? 'Тёмная тема' : 'Светлая тема');
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

    if (searchInput && dropdown) {
        searchInput.addEventListener('input', function () {
            const q = this.value.trim();
            if (q.length < 2) { dropdown.classList.remove('search__dropdown--open'); return; }
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

        async function fetchSuggestions(q) {
            try {
                const response = await fetch(`/api/v1/titles/search/?q=${encodeURIComponent(q)}&limit=6`, {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                });
                if (!response.ok) throw new Error('Search failed');
                const data = await response.json();
                renderSuggestions(data.results || data);
            } catch {
                dropdown.classList.remove('search__dropdown--open');
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
            dropdown.replaceChildren();
            if (!items || items.length === 0) {
                dropdown.appendChild(element('div', 'search__no-results', 'Ничего не найдено'));
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

                if (item.type === 'person') {
                    body.appendChild(element('span', 'search__suggestion-meta', 'Персона'));
                } else {
                    const kind = item.type === 'movie' ? 'Фильм' : 'Сериал';
                    const meta = [item.release_year || '', kind].filter(Boolean).join(' · ');
                    body.appendChild(element('span', 'search__suggestion-meta', meta));
                }

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
                track.scrollBy({ left: -scrollAmount(), behavior: 'smooth' });
                updateButtons();
            });
        }
        if (nextBtn) {
            nextBtn.addEventListener('click', function () {
                track.scrollBy({ left: scrollAmount(), behavior: 'smooth' });
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
        hamburger.addEventListener('click', function () {
            const isOpen = mobileNav.classList.toggle('mobile-nav--open');
            hamburger.classList.toggle('hamburger--active', isOpen);
            hamburger.setAttribute('aria-expanded', isOpen);
        });

        mobileNav.querySelectorAll('a').forEach(function (link) {
            link.addEventListener('click', function () {
                mobileNav.classList.remove('mobile-nav--open');
                hamburger.classList.remove('hamburger--active');
                hamburger.setAttribute('aria-expanded', 'false');
            });
        });
    }

    /* -----------------------------------------------
       5. Lightbox
    ----------------------------------------------- */
    const lightbox = document.querySelector('[data-lightbox]');
    const lightboxImg = document.querySelector('[data-lightbox-img]');
    const lightboxClose = document.querySelector('[data-lightbox-close]');

    if (lightbox && lightboxImg && lightboxClose) {
        document.querySelectorAll('[data-lightbox-trigger]').forEach(function (trigger) {
            trigger.addEventListener('click', function () {
                const src = this.dataset.lightboxTrigger || this.src;
                lightboxImg.src = src;
                lightbox.classList.add('lightbox--open');
                document.body.style.overflow = 'hidden';
            });
        });

        const closeLightbox = function () {
            lightbox.classList.remove('lightbox--open');
            document.body.style.overflow = '';
            lightboxImg.src = '';
        };

        lightboxClose.addEventListener('click', closeLightbox);
        lightbox.addEventListener('click', function (e) {
            if (e.target === lightbox) closeLightbox();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') closeLightbox();
        });
    }

    /* -----------------------------------------------
        6. Tabs
    ----------------------------------------------- */
    document.querySelectorAll('[data-tabs]').forEach(function (container) {
        // Контент вкладок лежит рядом с контейнером, а не внутри него:
        // в шаблонах это соседние <div class="tab-content">. Ищем в родителе.
        const scope = container.parentElement || document;
        const tabs = scope.querySelectorAll('[data-tab]');
        const contents = scope.querySelectorAll('[data-tab-content]');

        tabs.forEach(function (tab) {
            tab.addEventListener('click', function () {
                const target = this.dataset.tab;
                tabs.forEach(t => t.classList.remove('tab--active'));
                contents.forEach(c => c.classList.remove('tab-content--active'));
                this.classList.add('tab--active');
                const content = scope.querySelector(`[data-tab-content="${target}"]`);
                if (content) content.classList.add('tab-content--active');
            });
        });
    });

    /* -----------------------------------------------
       8. Trailer autoplay on hover (hero)
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
        9. Hero auto-rotation with smooth crossfade
    ----------------------------------------------- */
    const heroRotation = document.querySelector('[data-hero-rotation]');
    if (heroRotation) {
        const slides = heroRotation.querySelectorAll('[data-hero-slide]');
        const videos = heroRotation.querySelectorAll('[data-hero-video]');
        const dots = heroRotation.querySelectorAll('[data-hero-dot]');
        let current = 0;
        let interval = null;

        const playVideo = (index) => {
            const video = videos[index];
            if (video) {
                video.currentTime = 0;
                video.play().catch(() => {});
            }
        };

        const pauseAllVideos = (exceptIndex) => {
            videos.forEach((v, i) => {
                if (i !== exceptIndex) {
                    v.pause();
                }
            });
        };

        const showSlide = (index) => {
            slides.forEach((s, i) => {
                if (i === index) {
                    s.classList.remove('showcase__slide--prev');
                    s.classList.add('showcase__slide--active');
                    s.classList.add('showcase__slide--animating');
                } else if (i === current) {
                    s.classList.remove('showcase__slide--active');
                    s.classList.add('showcase__slide--prev');
                    // Remove animation class after transition
                    setTimeout(() => s.classList.remove('showcase__slide--animating'), 800);
                } else {
                    s.classList.remove('showcase__slide--active', 'showcase__slide--prev', 'showcase__slide--animating');
                }
            });
            dots.forEach((d, i) => {
                d.classList.toggle('showcase__dot-btn--active', i === index);
            });
            current = index;

            // Autoplay trailer for active slide
            playVideo(current);
            pauseAllVideos(current);
        };

        const startRotation = () => {
            if (slides.length <= 1) return;
            stopRotation();
            interval = setInterval(() => {
                showSlide((current + 1) % slides.length);
            }, 9000);
        };

        const stopRotation = () => {
            if (interval) {
                clearInterval(interval);
                interval = null;
            }
        };

        // Autoplay first video
        playVideo(0);

        // Dot click handlers
        dots.forEach((dot, i) => {
            dot.addEventListener('click', () => {
                showSlide(i);
                startRotation(); // reset timer
            });
        });

        // Pause on hover
        heroRotation.addEventListener('mouseenter', stopRotation);
        heroRotation.addEventListener('mouseleave', startRotation);

        startRotation();
    }

    /* -----------------------------------------------
       10. Toast notifications
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

    window.showToast = function (message, type = 'info', duration = 4000) {
        const container = document.querySelector('[data-toast-container]');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast toast--${type}`;
        toast.innerHTML = `
            ${TOAST_ICONS[type] || TOAST_ICONS.info}
            <span class="toast__message">${message}</span>
            <button class="toast__close" type="button" aria-label="Закрыть">${TOAST_CLOSE_ICON}</button>
        `;

        toast.querySelector('.toast__close').addEventListener('click', () => {
            toast.style.animation = 'toastOut 0.25s ease both';
            setTimeout(() => toast.remove(), 300);
        });

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
        11. Unified scroll handler
    ----------------------------------------------- */
    const header = document.querySelector('.site-header');
    let isScrolled = false;

    const scrollBar = (function () {
        const c = document.createElement('div');
        c.className = 'scroll-progress';
        c.innerHTML = '<div class="scroll-progress__bar" data-scroll-bar></div>';
        document.body.prepend(c);
        return c.querySelector('[data-scroll-bar]');
    })();

    const scrollBtn = document.querySelector('[data-scroll-top]');
    if (!scrollBtn) {
        const btn = document.createElement('button');
        btn.className = 'scroll-top';
        btn.setAttribute('data-scroll-top', '');
        btn.setAttribute('aria-label', 'Наверх');
        btn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"/></svg>';
        document.body.appendChild(btn);
        btn.addEventListener('click', () => {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }

    let scrollVisible = false;
    window.addEventListener('scroll', () => {
        const y = window.scrollY;
        const docHeight = document.documentElement.scrollHeight - window.innerHeight;

        // Scroll progress bar
        scrollBar.style.transform = 'scaleX(' + (docHeight > 0 ? (y / docHeight) : 0) + ')';

        // Header shadow
        if (header) {
            const shouldScroll = y > 10;
            if (shouldScroll !== isScrolled) {
                header.classList.toggle('site-header--scrolled', shouldScroll);
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
       12. Touch swipe for carousels
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
       13. Keyboard shortcuts (global)
    ----------------------------------------------- */
    document.addEventListener('keydown', function (e) {
        if (e.target.matches('input, select, textarea, [contenteditable]')) return;
        // / to focus search
        if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
            e.preventDefault();
            const input = document.querySelector('[data-search-input]');
            if (input) input.focus();
        }
    });

    /* -----------------------------------------------
       14. Card placeholder deterministic gradients
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
       15. Bottom-nav active link
    ----------------------------------------------- */
    {
        const nav = document.querySelector('.bottom-nav');
        if (nav) {
            const current = window.location.pathname;
            nav.querySelectorAll('.bottom-nav__link').forEach(function (link) {
                const href = link.getAttribute('href');
                if (href && href !== '#' && current.startsWith(href)) {
                    link.setAttribute('data-current', '');
                }
            });
        }
    }

})();
