/* Свои контролы для <video>.

   До этого видео проигрывалось нативным плеером браузера — с серой панелью
   Chrome поверх кадра. Это самая заметная деталь, которая выдаёт, что перед
   зрителем не продукт, а страница с тегом video.

   Разметка в шаблоне отдаёт <video controls>: без скрипта остаются нативные
   контролы, и смотреть кино всё равно можно. Скрипт снимает атрибут и берёт
   управление на себя — то есть отсутствие js ухудшает вид, но не ломает
   функциональность.

   Скрипт трогает только показ и управление. Переключение серий, выбор
   озвучки и сохранение позиции живут в title-detail.js и работают через тот
   же элемент <video>: они меняют источник и слушают события, а этот файл
   рисует состояние. Поэтому здесь нет ни одной записи в src.

   Для внешних плееров (iframe чужого сервиса) ничего этого нет и быть
   не может: там своя панель внутри чужого документа.
*/
(function () {
    'use strict';

    var shells = document.querySelectorAll('[data-vplayer]');
    if (!shells.length) return;

    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function formatTime(seconds) {
        if (!isFinite(seconds) || seconds < 0) seconds = 0;
        var total = Math.floor(seconds);
        var h = Math.floor(total / 3600);
        var m = Math.floor((total % 3600) / 60);
        var s = total % 60;
        var mm = h > 0 && m < 10 ? '0' + m : String(m);
        var ss = s < 10 ? '0' + s : String(s);
        return h > 0 ? h + ':' + mm + ':' + ss : mm + ':' + ss;
    }

    shells.forEach(function (shell) {
        var video = shell.querySelector('video');
        if (!video) return;

        var q = function (name) { return shell.querySelector('[data-vplayer-' + name + ']'); };
        var toggles = shell.querySelectorAll('[data-vplayer-toggle]');
        var seek = q('seek');
        var buffer = q('buffer');
        var current = q('current');
        var duration = q('duration');
        var muteBtn = q('mute');
        var volume = q('volume');
        var fullscreenBtn = q('fullscreen');
        var backBtn = q('back');
        var forwardBtn = q('forward');
        var spinner = q('spinner');
        var errorBox = q('error');
        var controls = q('controls');

        /* Нативную панель снимаем только сейчас, когда скрипт точно
           выполнился и свои контролы уже в разметке. */
        video.controls = false;
        shell.classList.add('vplayer--ready');

        /* ---------- Воспроизведение ---------- */

        function setPlayingState(playing) {
            shell.classList.toggle('vplayer--playing', playing);
            toggles.forEach(function (btn) {
                var label = playing ? btn.dataset.labelPause : btn.dataset.labelPlay;
                if (label) btn.setAttribute('aria-label', label);
            });
        }

        function togglePlay() {
            if (video.paused || video.ended) {
                var started = video.play();
                /* play() отдаёт промис, и браузер отклоняет его, если
                   воспроизведение запрещено политикой автозапуска. Без
                   перехвата это необработанная ошибка в консоли на каждый
                   такой случай. */
                if (started && typeof started.catch === 'function') {
                    started.catch(function () { setPlayingState(false); });
                }
            } else {
                video.pause();
            }
        }

        toggles.forEach(function (btn) {
            btn.addEventListener('click', togglePlay);
        });

        video.addEventListener('play', function () { setPlayingState(true); });
        video.addEventListener('pause', function () { setPlayingState(false); });
        video.addEventListener('ended', function () { setPlayingState(false); });

        /* ---------- Полоса времени ---------- */

        function renderProgress() {
            var total = video.duration;
            if (!isFinite(total) || total <= 0) return;
            var ratio = (video.currentTime / total) * 100;
            if (seek && !seek.matches(':active')) seek.value = String(ratio);
            if (seek) seek.setAttribute('aria-valuetext', formatTime(video.currentTime));
            shell.style.setProperty('--vplayer-progress', ratio + '%');
            if (current) current.textContent = formatTime(video.currentTime);
        }

        function renderBuffer() {
            var total = video.duration;
            if (!buffer || !isFinite(total) || total <= 0 || !video.buffered.length) return;
            var end = video.buffered.end(video.buffered.length - 1);
            shell.style.setProperty('--vplayer-buffer', (end / total) * 100 + '%');
        }

        video.addEventListener('timeupdate', renderProgress);
        video.addEventListener('progress', renderBuffer);

        video.addEventListener('loadedmetadata', function () {
            if (duration) duration.textContent = formatTime(video.duration);
            renderProgress();
            renderBuffer();
        });

        /* Источник меняется при переключении серии или озвучки: показания
           надо сбросить, иначе на новой серии секунду висит время прошлой. */
        video.addEventListener('emptied', function () {
            if (current) current.textContent = formatTime(0);
            if (duration) duration.textContent = formatTime(0);
            if (seek) seek.value = '0';
            shell.style.setProperty('--vplayer-progress', '0%');
            shell.style.setProperty('--vplayer-buffer', '0%');
            hideError();
        });

        if (seek) {
            seek.addEventListener('input', function () {
                var total = video.duration;
                if (!isFinite(total) || total <= 0) return;
                var time = (Number(seek.value) / 100) * total;
                shell.style.setProperty('--vplayer-progress', seek.value + '%');
                if (current) current.textContent = formatTime(time);
            });
            seek.addEventListener('change', function () {
                var total = video.duration;
                if (!isFinite(total) || total <= 0) return;
                video.currentTime = (Number(seek.value) / 100) * total;
            });
        }

        function nudge(delta) {
            if (!isFinite(video.duration)) return;
            video.currentTime = Math.min(
                Math.max(0, video.currentTime + delta),
                video.duration
            );
        }

        if (backBtn) backBtn.addEventListener('click', function () { nudge(-10); });
        if (forwardBtn) forwardBtn.addEventListener('click', function () { nudge(10); });

        /* ---------- Звук ---------- */

        function renderVolume() {
            var muted = video.muted || video.volume === 0;
            shell.classList.toggle('vplayer--muted', muted);
            if (volume) volume.value = String(muted ? 0 : video.volume);
            if (muteBtn) {
                var label = muted ? muteBtn.dataset.labelOn : muteBtn.dataset.labelOff;
                if (label) muteBtn.setAttribute('aria-label', label);
            }
        }

        if (muteBtn) {
            muteBtn.addEventListener('click', function () {
                video.muted = !video.muted;
                /* Звук на нуле и снятие «тихо» — противоречие: возвращаем
                   слышимую громкость, иначе кнопка выглядит сломанной. */
                if (!video.muted && video.volume === 0) video.volume = 0.5;
            });
        }

        if (volume) {
            volume.addEventListener('input', function () {
                video.volume = Number(volume.value);
                video.muted = video.volume === 0;
            });
        }

        video.addEventListener('volumechange', renderVolume);

        /* ---------- Полный экран ---------- */

        function inFullscreen() {
            return document.fullscreenElement === shell ||
                document.webkitFullscreenElement === shell;
        }

        function toggleFullscreen() {
            if (inFullscreen()) {
                if (document.exitFullscreen) document.exitFullscreen();
                else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
                return;
            }
            if (shell.requestFullscreen) shell.requestFullscreen();
            else if (shell.webkitRequestFullscreen) shell.webkitRequestFullscreen();
            /* iPhone не умеет полный экран для произвольного элемента —
               только для самого видео, и там панель будет системная. */
            else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
        }

        if (fullscreenBtn) fullscreenBtn.addEventListener('click', toggleFullscreen);

        document.addEventListener('fullscreenchange', function () {
            var on = inFullscreen();
            shell.classList.toggle('vplayer--fullscreen', on);
            if (fullscreenBtn) {
                var label = on ? fullscreenBtn.dataset.labelOff : fullscreenBtn.dataset.labelOn;
                if (label) fullscreenBtn.setAttribute('aria-label', label);
            }
        });

        /* ---------- Загрузка и ошибка ---------- */

        function showSpinner(on) {
            if (spinner) spinner.hidden = !on;
        }

        function hideError() {
            if (errorBox) errorBox.hidden = true;
        }

        video.addEventListener('waiting', function () { showSpinner(true); });
        video.addEventListener('stalled', function () { showSpinner(true); });
        video.addEventListener('playing', function () { showSpinner(false); hideError(); });
        video.addEventListener('canplay', function () { showSpinner(false); });

        /* Смена источника (серия, озвучка) начинается с load(): старое
           сообщение прячем сразу, иначе оно висит поверх нового кадра. */
        video.addEventListener('loadstart', function () {
            hideError();
            shell.classList.remove('vplayer--error');
        });

        /* Отказ источника раньше не показывался никак: кадр оставался
           чёрным, и зритель не мог отличить «не загрузилось» от «долго
           грузится». */
        function onMediaError() {
            showSpinner(false);
            if (errorBox) errorBox.hidden = false;
            setPlayingState(false);
            /* Приглашение к просмотру (большая кнопка) бесполезно, если
               источник не грузится, и перекрывает сообщение об ошибке. */
            shell.classList.add('vplayer--error');
        }

        /* 404 приходит не на <video>, а на его <source>: с источником
           в атрибуте src медиаэлемент сам сообщает об ошибке, с элементом
           <source> — нет, и кадр остаётся чёрным без объяснения. Ловим
           оба случая. */
        video.addEventListener('error', onMediaError);
        Array.prototype.forEach.call(video.querySelectorAll('source'), function (s) {
            s.addEventListener('error', onMediaError);
        });

        /* ---------- Панель прячется, когда не нужна ---------- */

        var hideTimer = null;

        function showControls() {
            shell.classList.remove('vplayer--idle');
            clearTimeout(hideTimer);
            if (video.paused) return;
            hideTimer = setTimeout(function () {
                /* Пока фокус внутри панели, прятать её нельзя: пользователь
                   клавиатуры потеряет то, на чём стоит. */
                if (controls && controls.contains(document.activeElement)) return;
                shell.classList.add('vplayer--idle');
            }, 2600);
        }

        ['mousemove', 'pointerdown', 'focusin'].forEach(function (name) {
            shell.addEventListener(name, showControls);
        });
        shell.addEventListener('mouseleave', function () {
            if (!video.paused) shell.classList.add('vplayer--idle');
        });
        video.addEventListener('pause', showControls);
        video.addEventListener('play', showControls);

        /* ---------- Клавиатура ---------- */

        shell.addEventListener('keydown', function (event) {
            /* Внутри ползунков стрелки — их собственная работа: перехват
               сделал бы регулировку громкости невозможной. */
            var tag = (event.target.tagName || '').toLowerCase();
            if (tag === 'input' && event.key.indexOf('Arrow') === 0) return;

            var handled = true;
            switch (event.key) {
                case ' ':
                case 'k':
                case 'K':
                    togglePlay();
                    break;
                case 'ArrowLeft':
                    nudge(-5);
                    break;
                case 'ArrowRight':
                    nudge(5);
                    break;
                case 'ArrowUp':
                    video.volume = Math.min(1, video.volume + 0.1);
                    break;
                case 'ArrowDown':
                    video.volume = Math.max(0, video.volume - 0.1);
                    break;
                case 'm':
                case 'M':
                    video.muted = !video.muted;
                    break;
                case 'f':
                case 'F':
                    toggleFullscreen();
                    break;
                default:
                    handled = false;
            }
            if (handled) {
                event.preventDefault();
                showControls();
            }
        });

        /* Клик по кадру — пауза, как в любом плеере. На телефоне это
           показ панели: там тап по кадру должен будить контролы, а не
           останавливать фильм в момент, когда до него дотронулись. */
        video.addEventListener('click', function () {
            if (window.matchMedia('(hover: none)').matches) {
                showControls();
                return;
            }
            togglePlay();
        });

        if (reduceMotion) shell.classList.add('vplayer--no-motion');

        renderVolume();
        setPlayingState(!video.paused);
        showControls();
    });
})();
