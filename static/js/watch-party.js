/* Совместный просмотр внешнего плеера (Vibix WatchParty).

   Включается настройкой VIDEO_SERVICE_WATCH_PARTY: тег <ins> внешнего
   плеера получает data-sync="true" (его читает SDK сервиса), а панель
   плеера — data-sync-room/data-sync-user. Этот скрипт ждёт, пока SDK
   заменит <ins> на iframe, и инициализирует WatchParty с комнатой по
   адресу записи.

   Данные для комнаты читаются с панели, а не с <ins>: SDK внешнего
   плеера заменяет <ins> на iframe раньше, чем выполнится этот скрипт,
   и тег к этому моменту уже исчезает из DOM.

   Зрители одной страницы попадают в одну комнату и смотрят синхронно:
   пауза, перемотка и переключение серий одного видны остальным.

   Скрипт ничего не ломает: без iframe (SDK не загрузился) или без
   WatchParty (sync-lib не пришёл) он молча выходит — плеер продолжает
   работать как обычно.
*/
(function () {
    'use strict';

    var pane = document.querySelector('[data-player-pane="external"]');
    if (!pane) return;

    var roomId = pane.dataset.syncRoom;
    if (!roomId) return;

    // Анонимного зрителя отличаем случайным суффиксом: два гостя в одной
    // комнате не должны выглядеть одним пользователем.
    var username = pane.dataset.syncUser || 'guest-' + Math.random().toString(36).slice(2, 8);

    function initWatchParty(iframe) {
        if (typeof WatchParty === 'undefined') return;
        try {
            new WatchParty({
                iframe: iframe,
                roomId: roomId,
                username: username,
                debug: false,
            });
        } catch (err) {
            // Плеер без совместного просмотра всё равно работает.
        }
    }

    // SDK внешнего плеера создаёт iframe из тега <ins> после загрузки;
    // ждём его с интервалом. 30 попыток по полсекунды — запас на медленную
    // сеть, дальше ждать бессмысленно.
    var attempts = 0;
    var timer = window.setInterval(function () {
        var iframe = pane.querySelector('iframe');
        if (iframe) {
            window.clearInterval(timer);
            initWatchParty(iframe);
            return;
        }
        if (++attempts >= 30) {
            window.clearInterval(timer);
        }
    }, 500);
})();