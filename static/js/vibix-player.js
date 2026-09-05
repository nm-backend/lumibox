/* Менеджер «затвора» перед плеером Vibix.
 
   Сервер рендерит только публичные ID в <ins>. Сам SDK Vibix подключается
   из <head> через блок extra_head шаблона — это нужно ему, чтобы авто-
   матически найти теги <ins> при загрузке страницы.
 
   Этот скрипт отвечает за:
   - скрытие кнопки «Начать» и превью, когда SDK отрисовал iframe;
   - показ сообщения об ошибке по таймауту, если iframe не появился;
   - мониторинг состояния плеера внутри iframe (ready/play/error);
   - fallback на трейлер если полное видео не загрузилось;
   - предотвращение двойной загрузки SDK.
 */
(function () {
    'use strict';
 
    var SDK_URLS = [
        'https://graphicslab.io/sdk/v2/rendex-sdk.min.js',
        'https://alt.graphicslab.io/sdk/v2/rendex-sdk.min.js',
    ];
    var LOAD_TIMEOUT_MS = 30000;
    var IFRAME_READY_TIMEOUT_MS = 15000;
    var HLS_LOAD_TIMEOUT_MS = 20000;
    var MAX_RETRY_ATTEMPTS = 2;
 
    function sdkLoaded() {
        return !!document.querySelector('script[data-lumibox-vibix-sdk]')
            || !!document.querySelector('script[src*="graphicslab.io"]');
    }
 
    function logEvent(pane, event, details) {
        var data = Object.assign({ event: event, timestamp: Date.now() }, details || {});
        console.log('[Vibix Player]', event, data);
        pane.dispatchEvent(new CustomEvent('lumibox:vibix-' + event, { detail: data }));
    }
 
    document.querySelectorAll('[data-vibix-player]').forEach(function (pane) {
        var button = pane.querySelector('[data-vibix-load]');
        var gate = pane.querySelector('[data-vibix-gate]');
        var status = pane.querySelector('[data-vibix-status]');
        var timeoutId = null;
        var observer = null;
        var iframeReadyTimer = null;
        var hlsLoadTimer = null;
        var failed = false;
        var retryCount = 0;
        var iframeLoaded = false;
        var playerReady = false;
        var trailerFallback = pane.dataset.vibixTrailerFallback === 'true';
 
        if (!gate || !button) {
            return;
        }
 
        var ins = pane.querySelector('ins');
        var originalType = ins ? ins.dataset.type : '';
        var originalId = ins ? ins.dataset.id : '';
        var isKpImdb = originalType === 'kp' || originalType === 'imdb';
        var trailerMode = ins ? ins.dataset.trailer : '';
 
        function iframeEl() {
            return pane.querySelector('iframe');
        }
 
        function clearWaiters() {
            if (observer) {
                observer.disconnect();
                observer = null;
            }
            if (timeoutId) {
                clearTimeout(timeoutId);
                timeoutId = null;
            }
            if (iframeReadyTimer) {
                clearTimeout(iframeReadyTimer);
                iframeReadyTimer = null;
            }
            if (hlsLoadTimer) {
                clearTimeout(hlsLoadTimer);
                hlsLoadTimer = null;
            }
        }
 
        function ready() {
            var frame = iframeEl();
            if (!frame) return false;
            if (playerReady) return true;
            playerReady = true;
            clearWaiters();
            pane.classList.remove('player--vibix-idle', 'player--vibix-loading', 'player--vibix-error');
            pane.classList.add('player--vibix-ready');
            gate.hidden = true;
            if (status) status.textContent = '';
            logEvent(pane, 'ready', { iframeSrc: frame.src });
            return true;
        }
 
        function tryTrailerFallback() {
            if (!trailerFallback || !isKpImdb || trailerMode === 'only') {
                return false;
            }
            var insEl = pane.querySelector('ins');
            if (!insEl) return false;
            logEvent(pane, 'trailer-fallback', { originalType: originalType, originalId: originalId });
            insEl.dataset.trailer = 'only';
            pane.classList.remove('player--vibix-ready', 'player--vibix-error');
            pane.classList.add('player--vibix-loading');
            gate.hidden = false;
            if (status) status.textContent = 'Загрузка трейлера…';
            playerReady = false;
            iframeLoaded = false;
            clearWaiters();
            waitForIframe();
            return true;
        }
 
        function showError(err) {
            if (ready()) return;
            if (tryTrailerFallback()) return;
            if (retryCount < MAX_RETRY_ATTEMPTS && isKpImdb) {
                retryCount++;
                logEvent(pane, 'retry', { attempt: retryCount, max: MAX_RETRY_ATTEMPTS });
                pane.classList.remove('player--vibix-ready', 'player--vibix-error');
                pane.classList.add('player--vibix-loading');
                if (status) status.textContent = 'Повторная попытка (' + retryCount + '/' + MAX_RETRY_ATTEMPTS + ')…';
                playerReady = false;
                iframeLoaded = false;
                clearWaiters();
                var frame = iframeEl();
                if (frame) frame.remove();
                waitForIframe();
                return;
            }
            failed = true;
            clearWaiters();
            pane.classList.remove('player--vibix-idle', 'player--vibix-loading');
            pane.classList.add('player--vibix-error');
            button.disabled = false;
            button.textContent = pane.dataset.vibixReload || 'Повторить загрузку';
            var msg = (err && err.message) ? err.message : (pane.dataset.vibixError || 'Внешний плеер не ответил. Попробуйте обновить страницу.');
            if (status) status.textContent = msg;
            logEvent(pane, 'error', { message: msg, retryCount: retryCount });
        }
 
        function onIframeLoad() {
            iframeLoaded = true;
            if (iframeReadyTimer) {
                clearTimeout(iframeReadyTimer);
                iframeReadyTimer = null;
            }
            logEvent(pane, 'iframe-load', { src: iframeEl().src });
            hlsLoadTimer = window.setTimeout(function() {
                if (!playerReady) {
                    var err = new Error('HLS load timeout');
                    err.code = 'HLS_TIMEOUT';
                    showError(err);
                }
            }, HLS_LOAD_TIMEOUT_MS);
        }
 
        function waitForIframe() {
            if (ready()) return;
            var frame = iframeEl();
            if (frame) {
                if (frame.src && frame.src !== 'about:blank') {
                    onIframeLoad();
                } else {
                    frame.addEventListener('load', onIframeLoad, { once: true });
                }
            }
            observer = new MutationObserver(function (mutations) {
                for (var i = 0; i < mutations.length; i++) {
                    if (mutations[i].addedNodes.length) {
                        var newFrame = iframeEl();
                        if (newFrame && newFrame !== frame) {
                            onIframeLoad();
                            break;
                        }
                    }
                }
            });
            observer.observe(pane, { childList: true, subtree: true });
            iframeReadyTimer = window.setTimeout(function() {
                if (!iframeLoaded) {
                    var err = new Error('Iframe creation timeout');
                    err.code = 'IFRAME_TIMEOUT';
                    showError(err);
                }
            }, IFRAME_READY_TIMEOUT_MS);
            timeoutId = window.setTimeout(showError, LOAD_TIMEOUT_MS);
        }
 
        function loadSdk() {
            if (ready()) return;
            if (failed && retryCount >= MAX_RETRY_ATTEMPTS) {
                window.location.reload();
                return;
            }
 
            button.disabled = true;
            pane.classList.remove('player--vibix-idle', 'player--vibix-error');
            pane.classList.add('player--vibix-loading');
            if (status) {
                status.textContent = pane.dataset.vibixLoading || 'Загрузка плеера…';
            }
            waitForIframe();
 
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
                    showError(new Error('SDK load failed'));
                }
            }, { once: true });
            document.head.appendChild(script);
        }
 
        window.addEventListener('message', function (event) {
            if (!event.data || event.data.type !== 'playerEvent') return;
            var frame = iframeEl();
            if (!frame || event.source !== frame.contentWindow) return;
            var evt = event.data.event;
            var time = event.data.time;
            logEvent(pane, 'player-event', { event: evt, time: time });
            if (evt === 'ready' || evt === 'start') {
                ready();
            } else if (evt === 'error') {
                showError(new Error('Player error: ' + evt));
            }
        });
 
        button.addEventListener('click', loadSdk);
        if (!ready()) {
            waitForIframe();
        }
    });
})();