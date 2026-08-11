/* Главная страница: выпадающие списки xSort (сортировка, подборка, год, страны).

   Поведение привязано к data-атрибутам, а не к классам оформления. Раньше файл
   целиком держался на .lb-xsort-area и .lb-xsort-div: переименование класса при
   правке стилей выключило бы все выпадашки главной молча — без ошибки в консоли
   и без единого падающего теста. Атрибут data-lb-dropdown для этого и был
   заведён в разметке, но скрипт его не читал.

   Класс-состояние lb-xsort-div--open остаётся классом: он и есть оформление,
   и переключать его — работа скрипта. */
(function () {
    'use strict';

    var root = document.querySelector('[data-lb-dropdowns]');
    if (!root) return;

    var OPEN = 'lb-xsort-div--open';

    function closeAll() {
        root.querySelectorAll('.' + OPEN).forEach(function (el) {
            el.classList.remove(OPEN);
            var trigger = el.querySelector('[data-lb-dropdown-trigger]');
            if (trigger) trigger.setAttribute('aria-expanded', 'false');
        });
    }

    root.addEventListener('click', function (event) {
        var dropdown = event.target.closest('[data-lb-dropdown]');
        if (!dropdown) return;
        var wasOpen = dropdown.classList.contains(OPEN);
        closeAll();
        if (!wasOpen) {
            dropdown.classList.add(OPEN);
            var trigger = dropdown.querySelector('[data-lb-dropdown-trigger]');
            if (trigger) trigger.setAttribute('aria-expanded', 'true');
        }
    });

    document.addEventListener('click', function (event) {
        if (root.contains(event.target)) return;
        closeAll();
    });

    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        var open = root.querySelector('.' + OPEN);
        if (!open) return;
        closeAll();
        var trigger = open.querySelector('[data-lb-dropdown-trigger]');
        if (trigger) trigger.focus();
    });
})();
