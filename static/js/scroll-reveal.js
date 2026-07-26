/*
  Scroll reveal — появление секций при скролле.

  Использует IntersectionObserver вместо scroll-событий:
  браузер сам通知, когда элемент попадает в viewport,
  и не тратит CPU на проверку позиции каждого кадра.

  Работает только если браузер поддерживает IntersectionObserver.
  Если не поддерживает — секции видны сразу (graceful degradation).

  Уважает prefers-reduced-motion: если пользователь отключил анимации,
  секции появляются мгновенно.
*/
(() => {
    /* Не запускаем, если пользователь отключил анимации */
    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;

    /* Не запускаем, если нет IntersectionObserver */
    if (!("IntersectionObserver" in window)) return;

    const sections = document.querySelectorAll(".section, .ad-banner, .collection-grid");

    if (!sections.length) return;

    /* Скрываем секции до появления в viewport */
    sections.forEach((section) => {
        section.style.opacity = "0";
        section.style.transform = "translateY(24px)";
        section.style.transition = "opacity 0.5s ease, transform 0.5s ease";
    });

    const observer = new IntersectionObserver(
        (entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.style.opacity = "1";
                    entry.target.style.transform = "translateY(0)";
                    observer.unobserve(entry.target);
                }
            });
        },
        {
            threshold: 0.1,
            rootMargin: "0px 0px -60px 0px",
        }
    );

    sections.forEach((section) => observer.observe(section));
})();
