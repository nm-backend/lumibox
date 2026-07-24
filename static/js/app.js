/* Main MovieHub application JS */

(function () {
    'use strict';

    /* -----------------------------------------------
       1. Theme toggle (dark/light)
    ----------------------------------------------- */
    const themeToggle = document.querySelector('[data-theme-toggle]');
    const html = document.documentElement;
    const stored = localStorage.getItem('moviehub-theme');
    if (stored) html.dataset.theme = stored;
    if (themeToggle) {
        const updateIcon = () => {
            themeToggle.textContent = html.dataset.theme === 'light' ? '🌙' : '☀️';
            themeToggle.setAttribute('aria-label', html.dataset.theme === 'light' ? 'Тёмная тема' : 'Светлая тема');
        };
        updateIcon();
        themeToggle.addEventListener('click', () => {
            html.dataset.theme = html.dataset.theme === 'light' ? '' : 'light';
            localStorage.setItem('moviehub-theme', html.dataset.theme);
            updateIcon();
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

        function renderSuggestions(items) {
            dropdown.innerHTML = '';
            if (!items || items.length === 0) {
                dropdown.innerHTML = '<div class="search__no-results">Ничего не найдено</div>';
                dropdown.classList.add('search__dropdown--open');
                return;
            }
            const list = document.createElement('div');
            items.forEach(item => {
                const link = document.createElement('a');
                link.className = 'search__suggestion';
                link.href = item.url || `/title/${item.slug}/`;
                link.innerHTML = `
                    ${item.poster
                        ? `<img class="search__suggestion-poster" src="${item.poster}" alt="" loading="lazy">`
                        : `<span class="search__suggestion-poster-placeholder">${(item.name || '?')[0]}</span>`
                    }
                    <span class="search__suggestion-body">
                        <span class="search__suggestion-name">${item.name}</span>
                        <span class="search__suggestion-meta">${item.release_year || ''}${item.type ? ' · ' + (item.type === 'movie' ? 'Фильм' : 'Сериал') : ''}</span>
                    </span>
                `;
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

        if (prevBtn) {
            prevBtn.addEventListener('click', function () {
                track.scrollBy({ left: -scrollAmount(), behavior: 'smooth' });
            });
        }
        if (nextBtn) {
            nextBtn.addEventListener('click', function () {
                track.scrollBy({ left: scrollAmount(), behavior: 'smooth' });
            });
        }

        const updateButtons = () => {
            if (prevBtn) prevBtn.style.display = track.scrollLeft <= 0 ? 'none' : '';
            if (nextBtn) {
                const maxScroll = track.scrollWidth - track.clientWidth;
                nextBtn.style.display = track.scrollLeft >= maxScroll - 5 ? 'none' : '';
            }
        };
        track.addEventListener('scroll', updateButtons);
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
       6. Scroll reveal animation
    ----------------------------------------------- */
    if ('IntersectionObserver' in window) {
        const revealObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add('reveal--visible');
                    revealObserver.unobserve(entry.target);
                }
            });
        }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

        document.querySelectorAll('.reveal').forEach(function (el) {
            revealObserver.observe(el);
        });
    }

    /* -----------------------------------------------
       7. Tabs
    ----------------------------------------------- */
    document.querySelectorAll('[data-tabs]').forEach(function (container) {
        const tabs = container.querySelectorAll('[data-tab]');
        const contents = container.querySelectorAll('[data-tab-content]');

        tabs.forEach(function (tab) {
            tab.addEventListener('click', function () {
                const target = this.dataset.tab;
                tabs.forEach(t => t.classList.remove('tab--active'));
                contents.forEach(c => c.classList.remove('tab-content--active'));
                this.classList.add('tab--active');
                const content = container.querySelector(`[data-tab-content="${target}"]`);
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
       9. Hero auto-rotation
    ----------------------------------------------- */
    const heroRotation = document.querySelector('[data-hero-rotation]');
    if (heroRotation) {
        const slides = heroRotation.querySelectorAll('[data-hero-slide]');
        const dots = heroRotation.querySelectorAll('[data-hero-dot]');
        let current = 0;
        let interval = null;

        const showSlide = (index) => {
            slides.forEach((s, i) => {
                s.classList.toggle('showcase__slide--active', i === index);
            });
            dots.forEach((d, i) => {
                d.classList.toggle('showcase__dot-btn--active', i === index);
            });
            current = index;
        };

        const startRotation = () => {
            if (slides.length <= 1) return;
            stopRotation();
            interval = setInterval(() => {
                showSlide((current + 1) % slides.length);
            }, 7000);
        };

        const stopRotation = () => {
            if (interval) {
                clearInterval(interval);
                interval = null;
            }
        };

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

    window.showToast = function (message, type = 'info', duration = 4000) {
        const container = document.querySelector('[data-toast-container]');
        if (!container) return;

        const icons = {
            success: '✅',
            error: '❌',
            info: 'ℹ️',
        };

        const toast = document.createElement('div');
        toast.className = `toast toast--${type}`;
        toast.innerHTML = `
            <span class="toast__icon">${icons[type] || 'ℹ️'}</span>
            <span class="toast__message">${message}</span>
            <button class="toast__close" type="button" aria-label="Закрыть">✕</button>
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
       11. Scroll-to-top button
    ----------------------------------------------- */
    const scrollBtn = document.querySelector('[data-scroll-top]');
    if (!scrollBtn) {
        const btn = document.createElement('button');
        btn.className = 'scroll-top';
        btn.setAttribute('data-scroll-top', '');
        btn.setAttribute('aria-label', 'Наверх');
        btn.textContent = '↑';
        document.body.appendChild(btn);

        let scrollVisible = false;
        window.addEventListener('scroll', () => {
            const shouldShow = window.scrollY > 400;
            if (shouldShow !== scrollVisible) {
                btn.classList.toggle('scroll-top--visible', shouldShow);
                scrollVisible = shouldShow;
            }
        }, { passive: true });

        btn.addEventListener('click', () => {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }

    /* -----------------------------------------------
       12. Keyboard shortcuts (global)
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

})();
