/* Безопасная граница загрузки внешнего плеера Vibix.

   Сервер рендерит только публичные ID в <ins>. Mutable SDK Vibix не
   загружается при обычном открытии карточки: запрос к graphicslab.io и
   создание стороннего iframe начинаются после явного нажатия зрителя.
   Скрипт SDK добавляется динамически — это часть его публичного DOM-контракта.

   Этот скрипт отвечает за:
   - загрузку SDK по клику на кнопку «Начать»;
   - скрытие кнопки «Начать» и превью, когда SDK отрисовал iframe;
   - показ сообщения об ошибке по таймауту, если iframe не появился;
   - предотвращение повторной параллельной загрузки SDK.
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
            clearWaiters();
            pane.classList.remove('player--vibix-idle', 'player--vibix-loading');
            pane.classList.add('player--vibix-error');
            button.disabled = false;
            button.textContent = pane.dataset.vibixReload || 'Обновить';
            if (status) {
                status.textContent = pane.dataset.vibixError || 'Плеер не ответил. Проверьте соединение и попробуйте снова.';
            }
        }

        function waitForIframe() {
            if (ready()) return;
            clearWaiters();
            observer = new MutationObserver(function () {
                ready();
            });
            observer.observe(pane, { childList: true, subtree: true });
            timeoutId = window.setTimeout(showError, LOAD_TIMEOUT_MS);
        }

        function appendSdkScript(index) {
            var existing = document.querySelector('script[data-lumibox-vibix-sdk]');
            if (existing) {
                existing.remove();
            }
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

        function loadSdk() {
            if (ready()) return;

            button.disabled = true;
            pane.classList.remove('player--vibix-idle', 'player--vibix-error');
            pane.classList.add('player--vibix-loading');
            if (status) {
                status.textContent = pane.dataset.vibixLoading || 'Загружаем плеер…';
            }
            waitForIframe();

            if (sdkLoaded()) {
                /* Если SDK уже был подключён ранее, даём ему шанс найти ins или реинициализировать */
                return;
            }

            appendSdkScript(0);
        }

        button.addEventListener('click', loadSdk);
        ready();
    }

    document.querySelectorAll('[data-vibix-player]').forEach(initPlayer);
})();
