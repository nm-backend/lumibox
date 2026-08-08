/* Страница фильма: быстрая оценка звёздами, кнопки «Поделиться»,
   модальный плеер трейлера. Все значения из шаблона приходят
   через data-атрибуты. */
(function () {
    'use strict';

    function getCookie(name) {
        var value = '; ' + document.cookie;
        var parts = value.split('; ' + name + '=');
        if (parts.length === 2) return parts.pop().split(';').shift();
    }

    /* ---------- 1. Быстрая оценка звёздами ---------- */

    var ratingContainer = document.querySelector('[data-star-rating]');
    if (ratingContainer) {
        var stars = ratingContainer.querySelectorAll('[data-star]');
        var statusEl = ratingContainer.querySelector('[data-star-status]');
        var currentRating = parseInt(ratingContainer.dataset.current || '0', 10) || 0;
        var slug = ratingContainer.dataset.slug || '';
        var savedMsg = statusEl ? statusEl.dataset.savedMsg || '' : '';
        var errorMsg = statusEl ? statusEl.dataset.errorMsg || '' : '';

        function setStars(value) {
            stars.forEach(function (star) {
                var isActive = parseInt(star.dataset.value, 10) <= value;
                star.classList.toggle('star-rating__star--active', isActive);
                // Для скринридеров шкала ведёт себя как радиогруппа.
                star.setAttribute('aria-checked', String(isActive));
            });
        }

        function flashStatus(text) {
            if (!statusEl) return;
            statusEl.textContent = text;
            setTimeout(function () { statusEl.textContent = ''; }, 3000);
        }

        setStars(currentRating);

        /* Клавиатурная доступность: <label> без <input> не фокусируется,
           поэтому навешиваем роль радиогруппы и навигацию стрелками. */
        var widget = ratingContainer.querySelector('[data-star-rating-widget]');
        if (widget) widget.setAttribute('role', 'radiogroup');
        stars.forEach(function (star) {
            star.setAttribute('role', 'radio');
            star.setAttribute('aria-label', 'Оценка ' + star.dataset.value);
            star.tabIndex = -1;
        });
        if (stars[0]) stars[0].tabIndex = 0;
        stars.forEach(function (star) {
            star.addEventListener('focus', function () {
                stars.forEach(function (s) { s.tabIndex = s === star ? 0 : -1; });
            });
        });
        if (statusEl) statusEl.setAttribute('aria-live', 'polite');

        stars.forEach(function (star, index) {
            star.addEventListener('keydown', function (event) {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    star.click();
                } else if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
                    event.preventDefault();
                    stars[(index + 1) % stars.length].focus();
                } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
                    event.preventDefault();
                    stars[(index - 1 + stars.length) % stars.length].focus();
                }
            });
        });

        stars.forEach(function (star) {
            star.addEventListener('mouseenter', function () {
                setStars(parseInt(this.dataset.value, 10));
            });

            star.addEventListener('mouseleave', function () {
                setStars(currentRating);
            });

            star.addEventListener('click', function () {
                var value = parseInt(this.dataset.value, 10);
                if (value === currentRating) return;

                var xhr = new XMLHttpRequest();
                xhr.open('POST', '/api/v1/titles/' + slug + '/rate/');
                xhr.setRequestHeader('Content-Type', 'application/json');
                xhr.setRequestHeader('X-CSRFToken', getCookie('csrftoken'));
                xhr.onload = function () {
                    if (xhr.status === 200) {
                        currentRating = value;
                        setStars(value);
                        flashStatus(savedMsg);
                    } else {
                        flashStatus(errorMsg);
                    }
                };
                xhr.onerror = function () { flashStatus(errorMsg); };
                xhr.send(JSON.stringify({ rating: value }));
            });
        });
    }

    /* ---------- 2. Кнопки «Поделиться» ---------- */

    document.querySelectorAll('[data-share]').forEach(function (shareBtn) {
        shareBtn.addEventListener('click', function () {
            var url = window.location.href;
            var title = document.title;

            if (navigator.share) {
                navigator.share({ title: title, url: url }).catch(function () {});
                return;
            }

            /* Копируем ссылку: современный Clipboard API с фолбэком на
               execCommand для старых браузеров и http-окружений. */
            function copyToClipboard(text) {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    return navigator.clipboard.writeText(text);
                }
                var input = document.createElement('textarea');
                input.value = text;
                input.setAttribute('readonly', '');
                input.style.position = 'fixed';
                input.style.opacity = '0';
                document.body.appendChild(input);
                input.select();
                try {
                    document.execCommand('copy');
                } catch (err) {
                    document.body.removeChild(input);
                    return Promise.reject(err);
                }
                document.body.removeChild(input);
                return Promise.resolve();
            }

            var copiedMsg = shareBtn.dataset.copiedMsg || '';
            copyToClipboard(url).then(function () {
                var original = shareBtn.innerHTML;
                shareBtn.textContent = copiedMsg;
                shareBtn.classList.add('sidebar-share__btn--copied');
                setTimeout(function () {
                    shareBtn.innerHTML = original;
                    shareBtn.classList.remove('sidebar-share__btn--copied');
                }, 2000);
            }).catch(function () {});
        });
    });

    /* ---------- 3. Модальный плеер трейлера ---------- */

    var modal = document.querySelector('[data-trailer-modal]');
    var openBtn = document.querySelector('[data-trailer-open]');
    if (modal && openBtn) {
        var modalVideo = modal.querySelector('[data-trailer-video]');
        var modalFrame = modal.querySelector('[data-trailer-iframe]');
        var lastFocus = null;

        function openModal() {
            lastFocus = document.activeElement;
            modal.hidden = false;
            document.body.style.overflow = 'hidden';
            if (modalVideo) modalVideo.play().catch(function () {});
            if (modalFrame && !modalFrame.getAttribute('src')) modalFrame.src = modalFrame.dataset.src;
            var close = modal.querySelector('[data-trailer-close]');
            if (close) close.focus();
        }

        function closeModal() {
            if (modal.hidden) return;
            modal.hidden = true;
            document.body.style.overflow = '';
            if (modalVideo) {
                modalVideo.pause();
                modalVideo.currentTime = 0;
            }
            if (modalFrame) modalFrame.src = '';
            if (lastFocus) lastFocus.focus();
        }

        openBtn.addEventListener('click', openModal);
        modal.querySelectorAll('[data-trailer-close]').forEach(function (close) {
            close.addEventListener('click', closeModal);
        });
        modal.addEventListener('click', function (event) {
            if (event.target === modal) closeModal();
        });
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && !modal.hidden) closeModal();
        });
    }

    /* ---------- 4. Плеер серий: переключение эпизодов ---------- */

    var playerVideo = document.querySelector('[data-player-video]');
    if (playerVideo) {
        var source = playerVideo.querySelector('[data-player-source]');
        var section = playerVideo.closest('.player-section');
        var buttons = section ? section.querySelectorAll('[data-episode]') : [];
        var currentLabel = section ? section.querySelector('[data-player-label]') : null;
        var titleSlug = section ? section.dataset.titleSlug : '';

        /* Прогресс просмотра: анонимно не пишем — сервер сам откажет,
           но и лишний запрос от гостя ни к чему. */
        function reportProgress(episodeId) {
            if (!episodeId || !titleSlug) return;
            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/v1/titles/' + titleSlug + '/watch/');
            xhr.setRequestHeader('Content-Type', 'application/json');
            xhr.setRequestHeader('X-CSRFToken', getCookie('csrftoken'));
            xhr.send(JSON.stringify({ episode: episodeId }));
        }

        function setEpisode(btn) {
            buttons.forEach(function (b) {
                b.classList.remove('player-episode--active');
            });
            btn.classList.add('player-episode--active');
            if (source && btn.dataset.episodeFile) {
                source.src = btn.dataset.episodeFile;
            }
            playerVideo.load();
            playerVideo.play().catch(function () {});
            if (currentLabel && btn.dataset.episodeLabel) {
                currentLabel.textContent = btn.dataset.episodeLabel;
            }
            reportProgress(btn.dataset.episodeId);
        }

        buttons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                setEpisode(btn);
            });
        });

        /* Название текущей серии в подписи плеера при загрузке:
           оно есть у первой (активной) кнопки. */
        var active = section ? section.querySelector('.player-episode--active') : null;
        if (active && currentLabel && active.dataset.episodeLabel) {
            currentLabel.textContent = active.dataset.episodeLabel;
        }
    }

    /* ---------- 4. Вкладки мультиплеера (Плеер 1 | Плеер 2 | Трейлер) ---------- */

    var playerTabs = document.querySelector('[data-player-tabs]');
    if (playerTabs) {
        var tabButtons = playerTabs.querySelectorAll('[data-player-tab]');
        var panes = document.querySelectorAll('[data-player-pane]');

        function selectPlayerTab(name) {
            tabButtons.forEach(function (btn) {
                var isActive = btn.dataset.playerTab === name;
                btn.classList.toggle('player-tabs__tab--active', isActive);
                btn.setAttribute('aria-selected', String(isActive));
                if (isActive) btn.tabIndex = 0;
                else btn.tabIndex = -1;
            });
            panes.forEach(function (pane) {
                var isActive = pane.dataset.playerPane === name;
                pane.hidden = !isActive;
            });
            /* Переключение источника у видео-панели: при возврате на
               «Плеер 1» восстанавливаем выбранную серию. */
            if (name === 'player1') {
                var videoPane = document.querySelector('[data-player-pane="player1"]');
                var video = videoPane ? videoPane.querySelector('video') : null;
                if (video) video.load();
            }
        }

        tabButtons.forEach(function (btn, index) {
            btn.addEventListener('click', function () {
                selectPlayerTab(btn.dataset.playerTab);
            });
            btn.addEventListener('keydown', function (event) {
                if (event.key === 'ArrowRight') {
                    var next = tabButtons[(index + 1) % tabButtons.length];
                    next.focus();
                    selectPlayerTab(next.dataset.playerTab);
                } else if (event.key === 'ArrowLeft') {
                    var prev = tabButtons[(index - 1 + tabButtons.length) % tabButtons.length];
                    prev.focus();
                    selectPlayerTab(prev.dataset.playerTab);
                }
            });
        });

        /* Роли для корректной работы со скринридером: роль tablist
           вешаем прямо в разметке, здесь — только навигация. */
        tabButtons.forEach(function (btn, index) {
            btn.tabIndex = index === 0 ? 0 : -1;
        });
    }
})();
