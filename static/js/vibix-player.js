/* Менеджер «затвора» перед плеером Vibix.

   Сервер рендерит только публичные ID в <ins>. Сам SDK Vibix подключается
   из <head> через блок extra_head шаблона — это нужно ему, чтобы авто-
   матически найти теги <ins> при загрузке страницы.

   Этот скрипт отвечает за:
   - скрытие кнопки «Начать» и превью, когда SDK отрисовал iframe;
   - показ сообщения об ошибке по таймауту, если iframe не появился;
   - предотвращение двойной загрузки SDK (если пользователь кликнул
     кнопку, пока SDK уже загружается из <head>).
*/
(function () {
    'use strict';

    /* Официальная инструкция Vibix даёт два адреса SDK: основной и резервный
       alt-домен на случай недоступности первого. Пробуем по порядку. */
    var SDK_URLS = [
        'https://graphicslab.io/sdk/v2/rendex-sdk.min.js',
        'https://alt.graphicslab.io/sdk/v2/rendex-sdk.min.js',
    ];
    var LOAD_TIMEOUT_MS = 20000;

    /* SDK, загруженный из <head>, не имеет data-lumibox-vibix-sdk.
       Ищем по URL для профилактики двойного запроса при клике. */
    function sdkLoaded() {
        return !!document.querySelector('script[data-lumibox-vibix-sdk]')
            || !!document.querySelector('script[src*="graphicslab.io"]');
    }

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

            /* SDK уже загружен из <head> — не дублируем запрос */
            if (sdkLoaded()) return;

            appendSdkScript(0);
        }

        function appendSdkScript(index) {
            var script = document.createElement('script');
            script.src = SDK_URLS[index];
            script.async = true;
            script.referrerPolicy = 'no-referrer';
            script.dataset.lumiboxVibixSdk = '1';
            script.addEventListener('error', function () {
                script.remove();
                if (index + 1 < SDK_URLS.length) {
                    appendSdkScript(index + 1);
                } else {
                    showError();
                }
            }, { once: true });
            document.head.appendChild(script);
        }

        button.addEventListener('click', loadSdk);
        /* Если iframe уже создан SDK из <head> — показываем плеер сразу.
           Иначе начинаем наблюдать: SDK может ещё загружаться. */
        if (!ready()) {
            waitForIframe();
        }
    }

    document.querySelectorAll('[data-vibix-player]').forEach(initPlayer);
})();
