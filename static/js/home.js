/* Главная страница: выпадающие списки xSort (сортировка, подборка, год, страны). */
(function () {
    'use strict';

    var root = document.querySelector('.kg-xsort-area');
    if (!root) return;

    root.addEventListener('click', function (event) {
        var div = event.target.closest('.kg-xsort-div');
        if (!div) return;
        var wasOpen = div.classList.contains('kg-xsort-div--open');
        root.querySelectorAll('.kg-xsort-div--open').forEach(function (el) {
            el.classList.remove('kg-xsort-div--open');
        });
        if (!wasOpen) div.classList.add('kg-xsort-div--open');
    });

    document.addEventListener('click', function (event) {
        if (root.contains(event.target)) return;
        root.querySelectorAll('.kg-xsort-div--open').forEach(function (el) {
            el.classList.remove('kg-xsort-div--open');
        });
    });

    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        root.querySelectorAll('.kg-xsort-div--open').forEach(function (el) {
            el.classList.remove('kg-xsort-div--open');
        });
    });
})();
