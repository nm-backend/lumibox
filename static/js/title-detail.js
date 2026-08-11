/* Страница фильма: быстрая оценка звёздами, кнопки «Поделиться»,
   модальный плеер трейлера. Все значения из шаблона приходят
   через data-атрибуты. */
(function () {
    'use strict';

    function getCsrfToken() {
        // В проде CSRF_COOKIE_HTTPONLY=True: cookie недоступен JS,
        // токен берём из meta-тега, cookie — как фолбэк.
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (meta && meta.getAttribute('content')) return meta.getAttribute('content');
        var value = '; ' + document.cookie;
        var parts = value.split('; csrftoken=');
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
                var starValue = parseInt(star.dataset.value, 10);
                // Закрашены все звёзды до выбранной включительно.
                star.classList.toggle('star-rating__star--active', starValue <= value);
                // Для скринридеров шкала ведёт себя как радиогруппа:
                // состояние хранит настоящий input[type=radio] внутри label.
                // Отмечен ровно один — именно выбранный. Раньше здесь стояло
                // `checked = starValue <= value`, то есть true присваивался
                // всем звёздам до выбранной; сходилось лишь потому, что радио
                // одной группы гасят друг друга и последним оставался нужный.
                var input = star.querySelector('input[type="radio"]');
                if (input) input.checked = starValue === value;
            });
        }

        function flashStatus(text) {
            if (!statusEl) return;
            statusEl.textContent = text;
            setTimeout(function () { statusEl.textContent = ''; }, 3000);
        }

        setStars(currentRating);

        if (statusEl) statusEl.setAttribute('aria-live', 'polite');

        stars.forEach(function (star) {
            star.addEventListener('mouseenter', function () {
                setStars(parseInt(this.dataset.value, 10));
            });

            star.addEventListener('mouseleave', function () {
                setStars(currentRating);
            });

            star.addEventListener('click', function (event) {
                // Клик по label с input[type=radio] всплывает дважды:
                // сначала по label, потом с активированного radio. Второй
                // вариант — синтетический, с target=INPUT: игнорируем.
                if (event.target && event.target.tagName === 'INPUT') return;
                var value = parseInt(this.dataset.value, 10);
                if (value === currentRating) return;

                var xhr = new XMLHttpRequest();
                xhr.open('POST', '/api/v1/titles/' + slug + '/rate/');
                xhr.setRequestHeader('Content-Type', 'application/json');
                xhr.setRequestHeader('X-CSRFToken', getCsrfToken());
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
            if (event.key !== 'Tab' || modal.hidden) return;

            /* Фокус-ловушка. Без неё Tab из модалки уходил на страницу под
               ней: для зрячего это незаметно (окно перекрывает всё), а тот,
               кто ходит клавиатурой, оказывался в невидимом контенте и не
               понимал, куда попал. aria-modal о таком браузеру не сообщает —
               удержать фокус должен скрипт. */
            var focusable = modal.querySelectorAll(
                'button, [href], input, select, textarea, iframe, video, [tabindex]:not([tabindex="-1"])'
            );
            var visible = Array.prototype.filter.call(focusable, function (node) {
                return !node.hidden && node.offsetParent !== null;
            });
            if (!visible.length) return;

            var first = visible[0];
            var last = visible[visible.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        });
    }

    /* ---------- 4. Плеер серий: переключение эпизодов ---------- */

    var playerVideo = document.querySelector('[data-player-video]');
    if (playerVideo) {
        var source = playerVideo.querySelector('[data-player-source]');
        /* Секция ищется по data-атрибуту: на этой одной строке держатся выбор
           серии, выбор озвучки, сохранение прогресса и продолжение с секунды.
           Пока здесь стоял класс оформления, переименование .player-section при
           правке стилей выключило бы все четыре механики разом и молча.
           Класс оставлен вторым вариантом — на случай кэша старой разметки. */
        var section = playerVideo.closest('[data-player-section]') ||
            playerVideo.closest('.player-section');
        var buttons = section ? section.querySelectorAll('[data-episode]') : [];
        var currentLabel = section ? section.querySelector('[data-player-label]') : null;
        var titleSlug = section ? section.dataset.titleSlug : '';

        /* Прогресс просмотра: анонимно не пишем — сервер всё равно ответит 403.
           Раньше в комментарии это было обещано, а в коде проверки не было,
           и каждое переключение серии гостем давало отказ в консоли и в логах.
           Признак входа приходит из разметки: base.html ставит его на <body>. */
        var isAuthenticated = document.body.dataset.authenticated === '1';
        var currentEpisodeId = null;

        function sendProgress(payload) {
            if (!isAuthenticated || !titleSlug) return;
            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/v1/titles/' + titleSlug + '/watch/');
            xhr.setRequestHeader('Content-Type', 'application/json');
            xhr.setRequestHeader('X-CSRFToken', getCsrfToken());
            xhr.send(JSON.stringify(payload));
        }

        function reportProgress(episodeId) {
            currentEpisodeId = episodeId || currentEpisodeId;
            sendProgress({ episode: currentEpisodeId ? Number(currentEpisodeId) : null, position: 0 });
        }

        /* Позицию шлём не на каждый кадр таймкода, а раз в POSITION_INTERVAL
           секунд: timeupdate срабатывает несколько раз в секунду, и без
           ограничения плеер устроил бы серверу поток из сотен запросов
           на одного зрителя. */
        var POSITION_INTERVAL = 15;
        var lastSent = 0;

        function savePosition(force) {
            if (!isAuthenticated || !playerVideo) return;
            var position = Math.floor(playerVideo.currentTime || 0);
            if (!force && position - lastSent < POSITION_INTERVAL && position >= lastSent) return;
            lastSent = position;
            var duration = playerVideo.duration;
            sendProgress({
                episode: currentEpisodeId ? Number(currentEpisodeId) : null,
                position: position,
                duration: isFinite(duration) ? Math.floor(duration) : undefined,
            });
        }

        /* ---------- Источники: серия × озвучка ----------

           Плоский список приходит из разметки (json_script). Ищем в нём
           источник для текущей пары и подставляем: файл — в <video>,
           внешний плеер — в <iframe>. Обе оболочки уже в DOM, поэтому
           переключение типа сводится к показу одной и скрытию другой. */
        var playerFrame = section ? section.querySelector('[data-player-frame]') : null;
        var voiceButtons = section ? section.querySelectorAll('[data-voice]') : [];
        var currentVoiceId = null;
        var playbackData = [];

        var dataNode = document.getElementById('playback-data');
        if (dataNode) {
            try {
                playbackData = JSON.parse(dataNode.textContent) || [];
            } catch (e) {
                playbackData = [];
            }
        }

        function findSource(episodeId, voiceId) {
            var episode = episodeId ? Number(episodeId) : null;
            var voice = voiceId ? Number(voiceId) : null;
            var forEpisode = playbackData.filter(function (item) {
                return (item.episode || null) === episode;
            });
            if (!forEpisode.length) return null;
            var exact = forEpisode.filter(function (item) {
                return (item.voice || null) === voice;
            });
            /* Нужной озвучки у этой серии может не быть — тогда включаем
               первую доступную, а не оставляем зрителя перед пустым плеером. */
            return exact.length ? exact[0] : forEpisode[0];
        }

        /* Прячем и показываем оболочку плеера целиком, а не сам <video>:
           вокруг него теперь своя панель контролов, и скрытие одного видео
           оставило бы висеть кнопки от исчезнувшего кадра. Если оболочки
           нет (без своих контролов), работаем по-старому с самим элементом. */
        var videoShell = playerVideo.closest('[data-vplayer]') || playerVideo;

        function applySource(item) {
            if (!item) return;
            if (item.kind === 'file') {
                if (source) source.src = item.src;
                if (playerFrame) {
                    playerFrame.hidden = true;
                    playerFrame.removeAttribute('src');
                }
                videoShell.hidden = false;
                playerVideo.load();
                playerVideo.play().catch(function () {});
            } else if (playerFrame) {
                playerVideo.pause();
                videoShell.hidden = true;
                playerFrame.hidden = false;
                playerFrame.src = item.src;
            }
            currentVoiceId = item.voice || null;
            voiceButtons.forEach(function (btn) {
                var isActive = Number(btn.dataset.voice) === currentVoiceId;
                btn.classList.toggle('player-voices__item--active', isActive);
                btn.setAttribute('aria-pressed', String(isActive));
            });
        }

        voiceButtons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                applySource(findSource(currentEpisodeId, btn.dataset.voice));
            });
        });

        function setEpisode(btn) {
            buttons.forEach(function (b) {
                b.classList.remove('player-episode--active');
            });
            btn.classList.add('player-episode--active');
            currentEpisodeId = btn.dataset.episodeId || null;
            // Озвучку сохраняем между сериями: зритель выбрал её один раз.
            applySource(findSource(currentEpisodeId, currentVoiceId));
            if (currentLabel && btn.dataset.episodeLabel) {
                currentLabel.textContent = btn.dataset.episodeLabel;
            }
            lastSent = 0;
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
        if (active) currentEpisodeId = active.dataset.episodeId || null;

        // Начальную озвучку берём из уже отрисованной кнопки: разметка
        // и скрипт должны стартовать из одного состояния.
        var activeVoice = section ? section.querySelector('.player-voices__item--active') : null;
        if (activeVoice) currentVoiceId = Number(activeVoice.dataset.voice);

        /* Продолжение с сохранённой секунды.

           Перематываем один раз, на первых загруженных метаданных: делать
           это на каждый loadedmetadata значило бы возвращать зрителя назад
           после каждого переключения серии. */
        var resumeAt = parseInt(section ? section.dataset.resumePosition : '0', 10) || 0;
        if (resumeAt > 0) {
            playerVideo.addEventListener('loadedmetadata', function seekOnce() {
                playerVideo.removeEventListener('loadedmetadata', seekOnce);
                // За пару секунд до остановки: так легче поймать нить сцены.
                var target = Math.max(0, resumeAt - 2);
                if (!playerVideo.duration || target < playerVideo.duration) {
                    playerVideo.currentTime = target;
                    lastSent = target;
                }
            });
        }

        playerVideo.addEventListener('timeupdate', function () {
            savePosition(false);
        });
        // Пауза и уход со страницы — те моменты, когда позицию важно
        // записать точно, не дожидаясь очередного интервала.
        playerVideo.addEventListener('pause', function () {
            savePosition(true);
        });
        window.addEventListener('pagehide', function () {
            savePosition(true);
        });
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
            /* Ничего не перезагружаем. Панель всего лишь скрывается атрибутом
               hidden — элемент video остаётся в DOM вместе со своим временем
               и выбранной серией. Здесь стоял video.load() «для восстановления
               серии», но он сбрасывал позицию на ноль: зритель уходил на вкладку
               с трейлером, возвращался — и смотрел серию заново с начала.
               Источник меняет только setEpisode, там load() уместен. */
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

    /* ---------- 5. Ответ на комментарий ---------- */

    var commentForm = document.querySelector('[data-comment-form]');
    if (commentForm) {
        var parentInput = commentForm.querySelector('[data-comment-parent]');
        var replyingBox = commentForm.querySelector('[data-comment-replying]');
        var replyingText = commentForm.querySelector('[data-comment-replying-text]');
        var cancelReply = commentForm.querySelector('[data-comment-cancel]');
        var commentField = commentForm.querySelector('textarea');

        function setReplyTarget(id, label) {
            if (!parentInput) return;
            parentInput.value = id || '';
            if (replyingBox) replyingBox.hidden = !id;
            /* Подпись приходит из разметки: перевод делает шаблон, а не
               скрипт. Тот же приём, что в поиске по актёрам. */
            if (replyingText) replyingText.textContent = label || '';
            if (id && commentField) commentField.focus();
        }

        document.addEventListener('click', function (event) {
            var replyBtn = event.target.closest('[data-reply-to]');
            if (replyBtn) {
                setReplyTarget(replyBtn.dataset.replyTo, replyBtn.dataset.replyLabel);
                return;
            }
            if (event.target.closest('[data-comment-cancel]')) {
                setReplyTarget('', '');
            }
        });

        if (cancelReply) cancelReply.setAttribute('aria-label', cancelReply.textContent);
    }

    /* ---------- 10. Событие view_item (просмотр тайтла) ---------- */
    var trackSection = document.querySelector('[data-title-slug]');
    if (trackSection && window.lbTrack) {
        window.lbTrack('view_item', {
            'item_id': trackSection.getAttribute('data-title-slug'),
            'item_name': document.title,
        });
    }
})();
