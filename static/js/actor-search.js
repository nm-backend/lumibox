/* Поиск по актёру: автодополнение подсказок при вводе.
   Подсказки строятся узлами DOM и textContent, а не innerHTML: имя актёра
   приходит из базы и не должно исполняться как разметка в чужом браузере. */
(function () {
    'use strict';

    var input = document.querySelector('[data-actor-search-input]');
    var suggestions = document.querySelector('[data-actor-suggestions]');
    if (!input || !suggestions) return;

    var form = document.querySelector('[data-actor-search-form]');
    var searchUrl = form ? form.action : null;
    var emptyMsg = suggestions.getAttribute('data-empty-msg') || '';
    var projectsMsg = suggestions.getAttribute('data-projects-msg') || '';
    var timer = null;
    // Отменяем предыдущий запрос при новом вводе: медленный ответ
    // не должен перекрывать подсказки для свежего запроса.
    var currentRequest = null;

    input.addEventListener('input', function () {
        var q = this.value.trim();
        if (q.length < 2) {
            suggestions.classList.remove('actor-search__suggestions--open');
            if (currentRequest) { currentRequest.abort(); currentRequest = null; }
            return;
        }
        clearTimeout(timer);
        timer = setTimeout(function () { fetchActorSuggestions(q); }, 300);
    });

    document.addEventListener('click', function (e) {
        if (!e.target.closest('.actor-search__form-wrapper')) {
            suggestions.classList.remove('actor-search__suggestions--open');
        }
    });

    input.addEventListener('focus', function () {
        if (this.value.trim().length >= 2) {
            suggestions.classList.add('actor-search__suggestions--open');
        }
    });

    function fetchActorSuggestions(q) {
        if (!searchUrl) return;
        if (currentRequest) currentRequest.abort();
        var controller = new AbortController();
        currentRequest = controller;
        fetch(searchUrl + '?q=' + encodeURIComponent(q), {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            signal: controller.signal
        })
            .then(function (response) {
                if (!response.ok) throw new Error('Search failed');
                return response.json();
            })
            .then(function (data) {
                if (controller.signal.aborted) return;
                renderSuggestions(data.results || []);
            })
            .catch(function (error) {
                if (error && error.name === 'AbortError') return;
                suggestions.classList.remove('actor-search__suggestions--open');
            });
    }

    function element(tag, className, text) {
        var node = document.createElement(tag);
        node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function renderSuggestions(items) {
        suggestions.replaceChildren();
        if (!items || items.length === 0) {
            suggestions.appendChild(element('p', 'actor-search__suggestions-empty', emptyMsg));
            suggestions.classList.add('actor-search__suggestions--open');
            return;
        }
        items.forEach(function (item) {
            var link = document.createElement('a');
            link.className = 'actor-search__suggestion';
            link.href = item.url;

            if (item.photo) {
                var img = element('img', 'actor-search__suggestion-photo');
                img.src = item.photo;
                img.alt = '';
                img.loading = 'lazy';
                link.appendChild(img);
            } else {
                link.appendChild(
                    element('span', 'actor-search__suggestion-photo actor-search__suggestion-photo--placeholder', (item.name || '?')[0])
                );
            }

            var body = element('span', 'actor-search__suggestion-body');
            body.appendChild(element('span', 'actor-search__suggestion-name', item.name));

            var meta = item.film_count + ' ' + projectsMsg;
            if (item.original_name) meta += ' · ' + item.original_name;
            body.appendChild(element('span', 'actor-search__suggestion-meta', meta));

            link.appendChild(body);
            link.appendChild(element('span', 'actor-search__suggestion-arrow', '→'));
            suggestions.appendChild(link);
        });
        suggestions.classList.add('actor-search__suggestions--open');
    }
})();
