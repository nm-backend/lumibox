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
    const searchForm = document.querySelector('[data-search-form]');
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

        // Show/hide buttons based on scroll position
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

        // Close on link click
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
       9. Keyboard shortcuts (global)
    ----------------------------------------------- */
    document.addEventListener('keydown', function (e) {
        // Don't hijack inputs
        if (e.target.matches('input, select, textarea, [contenteditable]')) return;
        // / to focus search
        if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
            e.preventDefault();
            const input = document.querySelector('[data-search-input]');
            if (input) input.focus();
        }
    });

})();
