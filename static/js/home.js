/* Главная страница: выпадающие списки xSort (сортировка, подборка, год, страны). */
(function () {
    'use strict';

    var root = document.querySelector('.lb-xsort-area');
    if (!root) return;

    root.addEventListener('click', function (event) {
        var div = event.target.closest('.lb-xsort-div');
        if (!div) return;
        var wasOpen = div.classList.contains('lb-xsort-div--open');
        root.querySelectorAll('.lb-xsort-div--open').forEach(function (el) {
            el.classList.remove('lb-xsort-div--open');
        });
        if (!wasOpen) div.classList.add('lb-xsort-div--open');
    });

    document.addEventListener('click', function (event) {
        if (root.contains(event.target)) return;
        root.querySelectorAll('.lb-xsort-div--open').forEach(function (el) {
            el.classList.remove('lb-xsort-div--open');
        });
    });

    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        root.querySelectorAll('.lb-xsort-div--open').forEach(function (el) {
            el.classList.remove('lb-xsort-div--open');
        });
    });
})();
