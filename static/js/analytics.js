/* Аналитика и cookie-согласие.

   Google Analytics подключается только с явного согласия посетителя:
   без нажатия «Принять» на баннере не грузится ни один скрипт Google.
   Согласие хранится в localStorage (ld_cookie_consent), баннер показывается
   один раз. Если GA_MEASUREMENT_ID не задан — модуль ничего не делает.
 */
(function () {
    'use strict';

    var CONSENT_KEY = 'lb_cookie_consent';

    function gaId() {
        return window.lbGaId || '';
    }

    function hasConsent() {
        try {
            return localStorage.getItem(CONSENT_KEY) === '1';
        } catch (e) {
            return false;
        }
    }

    function setConsent() {
        try {
            localStorage.setItem(CONSENT_KEY, '1');
        } catch (e) { /* приватный режим — живём без GA */ }
    }

    function loadGtag(id) {
        var s = document.createElement('script');
        s.async = true;
        s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(id);
        document.head.appendChild(s);
        window.dataLayer = window.dataLayer || [];
        function gtag() { window.dataLayer.push(arguments); }
        window.gtag = gtag;
        gtag('js', new Date());
        gtag('config', id, {
            'cookie_flags': 'SameSite=Lax;Secure',
            'anonymize_ip': true,
        });
    }

    function showBanner() {
        var banner = document.getElementById('cookie-consent');
        if (!banner) return;
        var accept = banner.querySelector('.cookie-consent__accept');
        if (!accept) return;

        banner.classList.add('cookie-consent--visible');
        banner.setAttribute('aria-hidden', 'false');

        accept.addEventListener('click', function () {
            setConsent();
            banner.classList.remove('cookie-consent--visible');
            banner.setAttribute('aria-hidden', 'true');
            if (gaId()) loadGtag(gaId());
        });
    }

    function init() {
        if (!gaId()) return; // GA не настроен — баннер не нужен
        if (hasConsent()) {
            loadGtag(gaId());
        } else {
            showBanner();
        }
    }

    document.addEventListener('DOMContentLoaded', init);

    /* Базовое событие для страниц, у которых есть данные (см. title-detail.js). */
    window.lbTrack = function (eventName, params) {
        if (!gaId() || !hasConsent() || typeof window.gtag !== 'function') return;
        window.gtag('event', eventName, params || {});
    };
})();
