(function () {
    'use strict';

    document.querySelectorAll('[data-vibix-player]').forEach(function (pane) {
        var gate = pane.querySelector('[data-vibix-gate]');
        var button = pane.querySelector('[data-vibix-load]');

        if (!gate || !button) {
            return;
        }

        function checkPlayer() {
            var iframe = pane.querySelector('iframe');

            if (!iframe) {
                return;
            }

            gate.hidden = true;

            pane.classList.remove(
                'player--vibix-idle',
                'player--vibix-loading',
                'player--vibix-error'
            );

            pane.classList.add('player--vibix-ready');
        }

        var observer = new MutationObserver(checkPlayer);

        observer.observe(pane, {
            childList: true,
            subtree: true,
        });

        button.addEventListener('click', function () {
            button.disabled = true;

            pane.classList.remove(
                'player--vibix-idle',
                'player--vibix-error',
                'player--vibix-loading'
            );

            checkPlayer();
        });
    });
})();