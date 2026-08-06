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
                star.classList.toggle(
                    'star-rating__star--active',
                    parseInt(star.dataset.value, 10) <= value
                );
            });
        }

        function flashStatus(text) {
            if (!statusEl) return;
            statusEl.textContent = text;
            setTimeout(function () { statusEl.textContent = ''; }, 3000);
        }

        setStars(currentRating);

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

            var input = document.createElement('input');
            input.value = url;
            document.body.appendChild(input);
            input.select();
            document.execCommand('copy');
            document.body.removeChild(input);

            var copiedMsg = shareBtn.dataset.copiedMsg || '';
            var original = shareBtn.innerHTML;
            shareBtn.innerHTML = '<span>' + copiedMsg + '</span>';
            shareBtn.classList.add('sidebar-share__btn--copied');
            setTimeout(function () {
                shareBtn.innerHTML = original;
                shareBtn.classList.remove('sidebar-share__btn--copied');
            }, 2000);
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
})();
