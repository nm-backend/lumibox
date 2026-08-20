/* Безопасная граница загрузки внешнего плеера Vibix.

   Сервер рендерит только публичные ID в <ins>. Mutable SDK Vibix не
   загружается при обычном открытии карточки: запрос к graphicslab.io и
   создание стороннего iframe начинаются после явного нажатия зрителя.
   Скрипт SDK добавляется в <head> — это часть его публичного DOM-контракта.
*/
(function () {
    'use strict';

    var SDK_URL = 'https://graphicslab.io/sdk/v2/rendex-sdk.min.js';
    var LOAD_TIMEOUT_MS = 20000;

    function initPlayer(pane) {
        var button = pane.querySelector('[data-vibix-load]');
        var gate = pane.querySelector('[data-vibix-gate]');
        var status = pane.querySelector('[data-vibix-status]');
        var timeoutId = null;
        var observer = null;
        var failed = false;

        if (!button || !gate) return;

        function iframe() {
            return pane.querySelector('iframe');
        }

        function clearWaiters() {
            if (timeoutId !== null) {
                window.clearTimeout(timeoutId);
                timeoutId = null;
            }
            if (observer) {
                observer.disconnect();
                observer = null;
            }
        }

        function ready() {
            var frame = iframe();
            if (!frame) return false;
            clearWaiters();
            pane.classList.remove('player--vibix-idle', 'player--vibix-loading', 'player--vibix-error');
            pane.classList.add('player--vibix-ready');
            gate.hidden = true;
            if (status) status.textContent = '';
            window.dispatchEvent(new CustomEvent('lumibox:vibix-ready', {
                detail: { iframe: frame },
            }));
            return true;
        }

        function showError() {
            if (ready()) return;
            failed = true;
            clearWaiters();
            pane.classList.remove('player--vibix-idle', 'player--vibix-loading');
            pane.classList.add('player--vibix-error');
            button.disabled = false;
            button.textContent = pane.dataset.vibixReload || 'Reload page';
            if (status) {
                status.textContent = pane.dataset.vibixError || 'The external player did not respond.';
            }
        }

        function waitForIframe() {
            if (ready()) return;
            observer = new MutationObserver(function () {
                ready();
            });
            observer.observe(pane, { childList: true, subtree: true });
            timeoutId = window.setTimeout(showError, LOAD_TIMEOUT_MS);
        }

        function loadSdk() {
            if (ready()) return;
            if (failed) {
                window.location.reload();
                return;
            }

            button.disabled = true;
            pane.classList.remove('player--vibix-idle', 'player--vibix-error');
            pane.classList.add('player--vibix-loading');
            if (status) {
                status.textContent = pane.dataset.vibixLoading || 'Loading player…';
            }
            waitForIframe();

            var existing = document.querySelector('script[data-lumibox-vibix-sdk]');
            if (existing) return;

            var script = document.createElement('script');
            script.src = SDK_URL;
            script.async = true;
            script.referrerPolicy = 'no-referrer';
            script.dataset.lumiboxVibixSdk = '1';
            script.addEventListener('error', showError, { once: true });
            document.head.appendChild(script);
        }

        button.addEventListener('click', loadSdk);
        ready();
    }

    document.querySelectorAll('[data-vibix-player]').forEach(initPlayer);
})();
