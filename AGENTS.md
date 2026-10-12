# lumibox — Project Journal

Persistence anchor for this workspace's agent memory. The agent maintains this file:
append notable decisions, changes, and session notes so they survive across chats and
sessions. Newest entries on top. `get_project_briefing` reads the sections below.

## About

LumiBox is a full-featured online cinema and media portal built with Django, featuring multi-source video playback (Vibix external player SDK, YouTube fallback player, and byte-range local video player), rich catalog filtering, ratings, user reviews, collections, and mobile-first responsive design.

## Team Setup

### Quick Start (одна команда)
```bash
./start.sh          # macOS/Linux (Docker или Podman)
# или
start.bat           # Windows (Docker Desktop)
```

Скрипт сам: проверяет Docker/Podman, создаёт `.env` с сгенерированными паролями,
поднимает контейнеры, применяет миграции, наполняет каталог demo-данными.

### Ручной запуск (Podman на Fedora с SELinux)
```bash
# 1. .env уже должен быть в корне (см. .env.example)
# 2. Поднять контейнеры:
set -a && source .env && set +a && podman-compose up --build -d
# 3. Проверить:
podman-compose ps          # все 4 контейнера Up
podman-compose logs web    # entrypoint: миграции → каталог → админ
```

### Ключевые порты
| Сервис     | URL                              |
|------------|----------------------------------|
| Сайт       | http://localhost:8001/            |
| Админка    | http://localhost:8001/admin/      |
| Swagger    | http://localhost:8001/api/docs/   |
| PostgreSQL | localhost:5433 (user: lumibox)    |
| Redis      | localhost:6380                    |

### Важно для Fedora/SELinux
В `docker-compose.yml` volume mounts используют суффикс `:z` —
без него rootless Podman не может прочитать bind-mounted файлы.
Не удаляйте `:z` из volume definitions!

## Recent Changes

- **CI снова зелёный: атрибуты плеера Vibix, тег рекламной сети, Telegram в мобильной шапке**: закрыты все 5 предсуществующих падений (819 тестов → `OK`, 3 skip). (1) В `templates/catalog/title_detail.html` в тег `<ins>` вернулись `data-nopreload="true"` и `data-poster="true"`: они пропали вместе с откатом `b63819b` коммита `4fcf1aa` (в том откате была только пара атрибутов и косметика комментариев). Проверено в браузере: с ними SDK Vibix превращает `<ins>` (publisher `678503345`, тип `kp`, id `447301`) в iframe `…kinescopecdn.net/678503345/embed-kp/447301`, а зона плеера держит 16/9 (848×477 на 1280, 358×201 на 390) — то есть без прыжка вёрстки; без них `<ins>` остаётся пустым прямоугольником. (2) В `templates/base.html` добавлен корневой тег `<ins id="vibix_union" data-publisher_id data-add_types>` под флагом `ads_network.enabled`: лоадер в `<head>` был, а тега, который он ищет, не было ни в одном шаблоне. (3) Мобильная Telegram-ссылка: в HTML она была всегда (и на проде — `https://t.me/lumiboxxx` в шапке и в JSON-LD), а не видно её было из-за CSS — в `static/css/lumibox.css` перед блоком `@media (max-width: 480px)` стояла одинокая точка (остаток удалённого селектора), и браузер, считая её началом правила, съедал следующий блок целиком: стили ссылки не применялись никогда. Точка убрана, блок переписан (без `display`/`place-items`, чтобы иконка осталась в центре круга 44×44), правило `display: none` для ≤400px удалено — Telegram снова в шапке на всех ширинах. Место на 320–400px освобождает аватар (`.site-header__actions .user-menu`, его пункты есть в выдвижном меню), а правило зазора шапки на ≤400px получило нужную специфичность (`.site-header > .site-header__inner`) — до этого его перебивало `.site-header > .container` и зазор оставался 12px вместо 4px. Проверено: pixel sweep 300–430 с шагом 1px × 2 страницы × 2 состояния (524 замера) — от 320px ноль переполнений, запас между логотипом и рядом действий ≥4px; ниже 320px ряд заходит в боковой отступ (до 14.8px на 300px) без горизонтального скролла; все контролы 44×44 с иконкой в центре; `check`, ruff, mypy чисто; E2E (6 вьюпортов) — без переполнений.

- **Аудит вёрстки P0–P4: геометрия шапки, кнопки-иконки карточек, зазор каталога**: (P0) из `templates/catalog/title_detail.html` убраны маркеры конфликта слияния (`<<<<<<< HEAD` / `>>>>>>> 5c05520`) вместе с закомментированной `<span data-button-label>` внутри них; логика кнопок избранного и «смотреть позже», `aria-label` и `heart-filled` сохранены. Проверено `grep`-ом по `templates/`, `static/`, `apps/` — маркеров и `.orig`/`.rej` нет. (P1) `--header-height` 33px → 60px, `.site-header` переведён на `min-height` + `height:auto` (содержимое ~59–62px больше не режется линией), нижняя граница — `--color-border-strong`; добавлены токены `--topnav-height: 57px` и `--sticky-content-top: calc(header + topnav)`, так что navbar начинается ровно под шапкой, а sticky-сайдбар каталога и профиля отступает от низа строки разделов (было ~41px заезда под навигацию). На ≤400px Telegram скрыт из шапки — на 320px ряд действий вылезал за правый край на ~27px; тач-таргеты остальных кнопок сохранены. (P2) Из круглых кнопок карточек 40×40 убрана подпись `[data-button-label]` («В избранное», ~81px — вылезала за круг на соседнюю кнопку): подписи живут в `aria-label`/`title`, `favorite.js` после ответа сервера меняет иконку (`heart` ↔ `heart-filled`; у закладки заполненного символа нет — только класс), обновляет оба атрибута и остаётся на странице: гостю (`data-login-required`) показывается тост вместо ухода на `/login/`, ошибка запроса даёт тост `data-toast-error` без ложного успеха. Сохранённое состояние рисует prefetch (`card_state_prefetches` / `with_card_state` в `apps/catalog/managers.py`, подключён к `story_card_prefetches` и к спискам пользователя) — два запроса на страницу и только для вошедших. (P3) `.lb-contentwrap--home` gap 32px → 16px: на 1440px лента 485 → 501px при сайдбаре 331px, на ≤1024 сайдбар скрыт и пустой колонки нет. Проверено: `manage.py check` чист, 819 тестов (3 skip, те же 5 предсуществующих падений — `data-nopreload`/`data-poster`/`id="vibix_union"` в плеере и рекламной разметке), ruff check и mypy чистые; pixel sweep с шагом 1px (320–1920 × Home/Catalog/Title = 4803 ширины) — 0 нарушений; финальные замеры на 16 ширинах (320, 360, 375, 390, 414, 430, 480, 600, 768, 769, 900, 1024, 1025, 1280, 1440, 1920) — шапка ровно 60px, navbar на 60, контент с 133, gap 16, кнопки 40×40 без пересечений, 0 горизонтальных переполнений, sticky-сайдбар встаёт на 8px ниже навигации. Прод после деплоя: маркеров конфликта нет, в CSS лежит `gap: var(--space-4)`, гостевой клик по избранному/закладке остаётся на странице с тостом.

- **Точечный визуальный и UX-аудит вёрстки (без редизайна)**: закрыты пустые постер-области и мелкие дефекты вёрстки. (1) **Постеры**: причина чёрных прямоугольников — шаблоны смотрели только на локальный файл (`title.poster`), а у импортированного каталога заполнен лишь внешний `poster_url`, который намеренно не подгружается. Теперь каждая карточка всегда рендерит брендовую заглушку LumiBox (тёмная плёнка + акцентная иконка + название) и показывает её класса `is-visible`, если постера нет (работает без JS) либо если файл не открылся (`onerror`). Единый блок `.lb-poster-fallback` в `components.css` вместо пяти разрозненных заглушек; удалены мёртвые `.poster-card__fallback`/`.similar-card__placeholder`; `.film-hero__poster` и `.similar-card__poster` получили `position: relative` (без него заглушка растягивалась на всю страницу). (2) **Сайдбар**: восстановлен отсутствовавший CSS `.sb-films__placeholder` (строка схлопывалась до иконки 18px вместо бокса 48×64), добавлены разделители под заголовками групп, шаг между группами 20px, цвета метаданных подняты до `--color-text-muted`, группа «По странам» свёрнута по умолчанию через `<details>`/`<summary>` (тот же приём, что у панели фильтров, без JS). (3) **Пагинация**: пилюля текущей страницы выровнена по 38px с соседними номерами (правила «скина» перебивали основную ширину 26px), убран лишний фон, заголовок SEO-блока больше не дублируется. (4) **Типография**: бейджи карточек 11→12px, метаданные карточки 13→14px, мета сайдбара читаемее. (5) **Найден и исправлен предсуществующий баг мобильной вёрстки**: `!important` в `.film-card__body` делал мобильные `@media`-правки мёртвыми (на 320px текстовая колонка сжималась до 36px, значения метаданных — до нулевой ширины); на ≤700px подписи и значения переведены в одну колонку. (6) **SEO-блок** превращён из большой карточки в отделённый тонкой линией текст с иконкой и тем же содержимым. (7) Токен `--text-base` не существует — в двух местах заменён на `--text-md`, цвета заглушки переведены на `--color-dark-*` (в светлой теме подпись становилась почти чёрной на тёмной плёнке). Проверено: 819 тестов (814 OK, 5 предсуществующих падений по плееру Vibix и рекламной разметке — не связаны), `manage.py check` чист, 33 комбинации страница×ширина (320/768/1440) без горизонтального скролла и без JS-ошибок.

- **Редизайн и улучшение footer**: подвал сайта приведен к более чистому, премиальному и профессиональному виду без изменения остального дизайна. Блок разработчика обновлён: убраны «РУКОВОДИТЕЛЬ ПРОЕКТА» и текстовый формат «GitHub: nm-backend», выведено имя `Musajanov Nurullo` с двумя минималистичными ссылками-иконками (SVG GitHub и Telegram), ведущими на `https://github.com/nm-backend` и `https://t.me/nm_2110`. Убран дублирующий Telegram из правого нижнего угла подвала. В `icons.svg` добавлен символ `icon-telegram` (stroke-based вектор в общем стиле Feather/Tabler). Сохранены все правовые ссылки (18+, Политика конфиденциальности, Правообладателям, Пользовательское соглашение, Лицензия MIT) и копирайт © 2026 LumiBox. Проверена адаптивность на десктопе (1440px), планшете (768px) и смартфонах (375px, 320px) — элементы не ломают строку и не вызывают переполнения. Добавлен тест `FooterMarkupTests` в `apps/core/tests_views_extended.py`.
- **Vibix: приоритет KP/IMDb над устаревшим movie player_id**: на продакшен-странице `Начало` SDK уже загружался корректно, но HTML отдавал `data-type="movie" data-id="4427"`, после чего Vibix показывал «контент ещё не добавлен». Причина — сохранённый ранее `player_id` может устареть или быть неактуальным для аккаунта, а текущая инструкция Vibix официально поддерживает `data-type="kp"`/`imdb`. Для фильмов `_get_external_player()` теперь сначала отдаёт KP, затем IMDb, и только потом внутренний `player_id`; для сериалов валидный `series` embed остаётся приоритетным, чтобы сохранять сезон/серию.
- **Vibix trailer mode removed from embed**: после деплоя `Начало` уже отдавало `data-type="kp" data-id="447301"`, но также `data-trailer="true"`. Атрибут убран из `_get_external_player()` полностью, чтобы фильмы открывались обычным KP embed из актуальной инструкции Vibix независимо от старого окружения.
- **Актуализация SDK Vibix по инструкции партнёрского кабинета**: текущая инструкция требует оба асинхронных SDK (`graphicslab.io` и `alt.graphicslab.io`) в `<head>`. LumiBox теперь следует ей напрямую: удалены локальный overlay/gate и `vibix-player.js`, которые перекрывали нативный клик `data-nopreload` и могли не дать SDK создать iframe. Разметка `<ins>` и параметры (`movie|series|kp|imdb`, poster, season, episodes, voiceover, design) уже соответствовали контракту.
- **Исправление плеера Vibix на продакшене**: найдена главная причина неработающего плеера — у многих фильмов в базе данных было заполнено поле `player_id`, но поле `player_type` было пустым. Без `player_type` логика `_get_external_player()` не может определить тип плеера, и плеер не работает. Добавлена management команда `fix_player_types.py` для автоматического исправления: она находит все записи с `player_id` но без `player_type` и заполняет `player_type` на основе поля `is_series` (movie для фильмов, series для сериалов). Проверено на продакшене: после установки `player_type="movie"` для "Дьявол носит Prada 2" плеер начал работать корректно.
- **Предыдущее исправление SDK Vibix (заменено актуальной инструкцией)**: удалён глобальный тестовый тег из `base.html` (data-id="8036", data-type="series"), который конфликтовал с реальными плеерами на страницах фильмов. Проверка партнёрской инструкции позже показала, что способ с одним синхронным SDK устарел.
- **Полный каталог в локальной dev-БД + починка авто-логина Vibix**: правка `config/settings/base.py` — добавлены `VIBIX_USERNAME`/`VIBIX_PASSWORD` в `env.Env()` и проброс в settings; раньше `login_vibix()` не мог получить креды из `.env`, и документированный auto-fallback токена никогда не работал. Плюс ротация протухшего `VIBIX_API_TOKEN` в `.env` через `login_vibix()`. После этого локально импортирован весь каталог издателя (`sync_vibix --create-missing`, возобновляемым запуском после сетевого обрыва): 29 941 запись, DRAFT по умолчанию, `player_id` заполнен у 29 940/29 941 (единственная без — «Одна ночь», kp 5509288: на стороне Vibix embed-данных плеера нет вообще).
- **Массовый импорт каталога Vibix (`--create-missing`)**: новый режим в `sync_vibix` обходит весь список издателя и создаёт отсутствующие записи. Дедуп по kp_id (снимок + частичный уникальный индекс `title_kp_id_uniq_when_filled`, миграция 0026 с дедупликацией старых дублей), батчи по 500 через bulk_create, блокировка от параллельных прогонов (`VideoServiceSyncState.locked_at`, TTL 12 ч, `--unlock`), DRAFT по умолчанию, постеры через URL-поля `poster_url/backdrop_url` (без скачивания), серверный фильтр `type movie|serial` в клиенте, dry-run, прогресс, детальный отчёт, Celery-задача `create_missing_catalog`. Ядро: `bulk_create_from_catalog()` в `video_service_sync.py`. Проверено: 821 тест, ruff/mypy чистые, масштабный тест 5000 записей ≈2500 зап/с, возобновление после обрыва, живой импорт страниц каталога.
- **Секреты**: из `.env.example` удалён реальный Vibix-токен (считать скомпрометированным — ротировать!), исправлен `VIBIX_API_BASE_URL` на `https://api.vibix.org/api/v1`.
- **Vibix Integration & Auto-Recovery**: Refreshed Vibix API bearer token authentication, implemented `login_vibix` automatic authentication fallback, sanitized `fetch_video_links` limit parameter (20, 50, 100), and added graceful fallback from 403 detail endpoints to `/videos/links` catalog lookup.
- **Sync Architecture Hardening**: Updated `sync_title` in `apps/catalog/video_service_sync.py` to extract `player_id` from `embed_code` and sync series seasons/episodes seamlessly.
- **Automated Verification**: Added comprehensive test suite `apps/catalog/tests/test_vibix_e2e.py` and Playwright browser E2E test `tests_e2e_playwright.js` verifying player gate button, SDK injection, and 6 mobile viewports (320px–1440px) with zero overflow.

## Session Memory

### Session 2026-10-12 — Починка CI и возврат Telegram в мобильную шапку
- Локальный Chromium для Playwright: пакет 1.63.0 ждёт сборку 1243, а в кэше лежит 1234 → скрипты запускаются с `CHROME_PATH=%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe`.
- `tests_e2e_playwright.js` спавнит `python` из PATH и пишет `screenshot_*.png` в корень (он в `.gitignore`). Из-за внешних SDK выбранный там `networkidle` часто не наступает, а строка `Native Vibix lazy player tag found: false` — ожидаемая: к этому моменту SDK уже заменил `<ins>` на iframe.
- Артефакты этой сессии: `.freebuff/audit/tg_*.js` (замеры шапки, свипы 1px, скриншоты), `tg_sweep1px_problems.json`, `vibix_dom.js` / `vibix_size.js` (наблюдение за `<ins>` и iframe плеера).
- Урок: одиночная `.` в CSS-файле не безобидна — она молча убивает следующий блок правил. «Мёртвые» media-блоки нужно проверять браузером (`getComputedStyle`), а не чтением файла.
- `staticfiles/` — устаревшая копия `collectstatic`: в dev не отдаётся, но закоммичена. Правки делать в `static/`.

### Session 2026-10-12 — Аудит вёрстки P0–P4 (шапка, кнопки карточек, зазор)
- Локальная проверка: dev-сервер `manage.py runserver 127.0.0.1:8124` с `.env`; важно — после перезапуска Freebuff фоновые процессы умирают, сервер нужно поднимать заново.
- Форма входа на этом стенде ждёт **email** в поле с `name="username"` — логин по логину не проходит.
- Артефакты и скрипты аудита: `.freebuff/audit/` (Playwright `sweep1px.js`, `final_verify.js` + `final_analyze.py`, `prod_verify.js`, `prod/` и `p2_*`/`after*` — скриншоты и JSON-отчёты). Прод-скрипты запускаются с `AUDIT_BASE=https://lumibox.site`.
- `ruff format --check` в этом репозитории не enforced: те же три файла не проходят форматирование и на HEAD, поэтому ограничиваемся `ruff check` + `mypy` (оба чистые), а не массовым переформатированием.
- CI на GitHub красный **до** этих правок: 819 тестов, 5 предсуществующих падений (плеер Vibix: `data-nopreload`/`data-poster`; реклама: `id="vibix_union"`) — стоит починить отдельной задачей, иначе красный CI перестаёт что-либо значить.
- Коммит с правками: `1daee71` (12 файлов), обычным push в `main`, CD-Deploy зелёный; журнал обновлён отдельным коммитом.

### Session 2026-09-26 — Визуальный/UX-аудит: заглушки постеров, сайдбар, пагинация

- Рабочая точка: локальный dev-сервер (`manage.py runserver 127.0.0.1:8124`); важно — при `--noreload` изменения шаблонов не подхватываются живым процессом, нужен перезапуск (в браузере видно старую версию, CSS при этом обычно обновляется).
- Аудит без «насмотренности»: в этой сессии скриншоты не читались, поэтому геометрия и цвета проверялись числами через Playwright (`browser_evaluate`/`browser_run_code_unsafe`): `scrollWidth - clientWidth` на 320/375/480/768/1024/1440, размеры боксов, `getComputedStyle`, контраст по WCAG.
- `iframe` в отчётах не подходит: ответы сайта закрыты `X-Frame-Options`, `contentDocument` пустой. Мерять нужно через `page.setViewportSize()` + `page.evaluate()`.
- Градиенты/транзишены в этом headless-контексте не «доигрывают»: `getComputedStyle` отдаёт стартовое значение. Чтобы прочитать конечное — временно вставить `*,*::before,*::after{transition:none!important}`.
- Изменённые файлы: `static/css/components.css`, `static/css/lumibox.css`, `static/css/home_feed.css`, `static/css/title-detail.css`, `templates/includes/lb_sidebar.html`, `templates/includes/pagination.html`, `templates/catalog/title_detail.html`. Backend, модели, API, sync и плеер не менялись.
- Проверки: `check` — 0 issues; `manage.py test apps` — 819 тестов, 814 OK, 3 skip, 5 падений (все предсуществующие: тесты ждут `data-nopreload`/`data-poster` и `id="vibix_union"`, которых нет ни в одном шаблоне — в том числе в HEAD; к правкам вёрстки не относятся — важный сигнал владельцу); ruff/mypy не трогались (Python не менялся).
- Живьём проверено: заглушка совпадает с постер-боксом (178×268 в 180×270, hero 280×420), дорожка `onerror` (битая ссылка → картинка скрыта, заглушка показана), путь «настоящий постер» (заглушка `display: none`), свёрнутая группа открывается/закрывается с поворотом шеврона, строка сайдбара 80px с боксом 48×64, пагинация 38px с пилюлей активной страницы, светлая тема (текст заглушки #f5f5f7 на тёмной плёнке).
- Осторожно: для реалистичной проверки пагинации/сетки временно публиковалось 80 записей (список PK в `/tmp/lb_pub_added.txt`) — после проверки все возвращены в `draft`, в базе снова ровно 7 опубликованных.

### Session 2026-09-26 — Редизайн и оптимизация footer
- Обновлен `templates/includes/footer.html`: блок `.footer-credits` переведён на отображение `.footer-credits__label` («РАЗРАБОТКА»), `.footer-credits__name` («Musajanov Nurullo») и `.footer-credits__socials` с кликабельными ссылками-иконками GitHub и Telegram.
- Из `footer-bottom` удалена отдельная дублирующая ссылка на Telegram.
- Обновлен `static/css/footer.css` (и скопирован в `staticfiles/css/footer.css`): новые классы `.footer-credits__dev`, `.footer-credits__author`, `.footer-credits__social` с деликатными hover-состояниями (подсветка акцентным цветом `--color-accent`, мягкий фон, тень и сдвиг на 1px).
- В `static/img/icons.svg` (и `staticfiles/img/icons.svg`) добавлен символ `icon-telegram` в едином 24x24 стиле проекта.
- Проведено тестирование верстки и сняты контрольные скриншоты во всех брейкпоинтах (320px, 375px, 768px, 1440px).
- Все тесты `apps.core.tests_views_extended` успешно пройдены.

### Session 2026-09-11 — Актуализация подключения Vibix
- Пользователь прислал актуальную инструкцию партнёрского кабинета: обязательны оба скрипта с `async`: `graphicslab.io/sdk/v2/rendex-sdk.min.js` и `alt.graphicslab.io/sdk/v2/rendex-sdk.min.js`.
- Разметка LumiBox `<ins data-publisher-id data-type data-id>` и параметры `series`, `kp`, `imdb`, `data-poster`, `data-nopreload`, сезоны и озвучки соответствуют инструкции.
- Корень сбоя: ранее оставлялся один SDK без `async`, а локальный `vibix-player.js` накрывал нативный постер кнопкой и не пересылал клик на `<ins>`. При `data-nopreload` это могло оставить iframe несозданным до таймаута. Перешли на штатную лёгкую интеграцию SDK.

- Vibix API base URL: `https://api.vibix.org/api/v1`
- Publisher ID: `678503345` (User ID `1184`)
- Catalog size: 31,037 titles in `/publisher/videos/links`; заметная доля карточек без `kp_id` (~45% на первых страницах) — при массовом импорте они честно пропускаются
- Rendex SDK URL: `https://graphicslab.io/sdk/v2/rendex-sdk.min.js`
- Тесты `check_vibix` требуют герметичности: без override пустых кредов и патча `login_vibix` они подхватывают реальные данные `.env` и ходят в сеть

### Session 2026-09-11 — Исправление плеера Vibix на продакшене
- Диагноз главной проблемы: на продакшене lumibox.site плеер не работал, потому что у многих фильмов в базе данных было заполнено поле `player_id`, но поле `player_type` было пустым. Без `player_type` логика `_get_external_player()` в `views.py` не может определить тип плеера, и плеер не загружается.
- Проверка через админку lumibox.site: у фильма "Дьявол носит Prada 2" было `player_id="686838"` но `player_type=""`. После установки `player_type="movie"` плеер начал работать корректно.
- Исправление: добавлена management команда `fix_player_types.py` для автоматического исправления всех записей с `player_id` но без `player_type`. Команда заполняет `player_type` на основе поля `is_series` (movie для фильмов, series для сериалов).
- Команда запушена в репозиторий, GitHub Actions автоматически задеплоит на продакшен. После деплоя нужно выполнить `python manage.py fix_player_types` на продакшене.

### Session 2026-09-11 — Исправление SDK плеера Vibix
- Диагноз главной проблемы: в `base.html` был глобальный тестовый тег Vibix `<ins data-publisher-id="678503345" data-type="series" data-id="8036" ...></ins>`, который конфликтовал с реальными плеерами на страницах фильмов. SDK Vibix находил этот глобальный тег вместо конкретных плееров, что вызывало ошибку "Извините, запрашиваемый контент ещё не добавлен".
- Дополнительная проблема: в `base.html` были два скрипта SDK с `async` (основной и резервный), что нарушало инструкцию. Согласно инструкции должен быть один скрипт без `async`, а резервный должен загружаться динамически через JavaScript при ошибке.
- Исправления: (1) Удалён глобальный тестовый тег из `base.html`; (2) Оставлен только основной скрипт `graphicslab.io` без `async`; (3) Резервный скрипт `alt.graphicslab.io` загружается через `vibix-player.js` при сбое основного.
- Проверка: тестирование страницы фильма показало, что теги плеера рендерятся с правильными параметрами (player_id, player_type, publisher_id), старый тестовый тег отсутствует.

### Session 2026-09-06 — Полный импорт каталога в dev и авто-логин Vibix
- Диагноз двух крахов `sync_vibix`: (1) контейнеры Docker были подняты (демон Docker Desktop не запущен) → connection timeout на localhost:5433; (2) `VIBIX_API_TOKEN` в .env протух (401) → авто-логин не срабатывал, т.к. settings не читали `VIBIX_USERNAME`/`VIBIX_PASSWORD`. Оба исправлены.
- Правка `config/settings/base.py`: добавлены `VIBIX_USERNAME=(str, "")`, `VIBIX_PASSWORD=(str, "")` в `env.Env()` и проброс `VIBIX_USERNAME = env(...)` / `VIBIX_PASSWORD = env(...)` рядом с Vibix-блоком. Мypy/ruff: изменённый файл чист (mypy падает на предсуществующем `apps/core/py314_compat.py:30 cannot assign to a method` — не наше).
- Актуальный размер каталога: 31 964 карточки в `/videos/links` (320 страниц по 100). Импорт: создано 29 940 записей суммарно (первый заход: 16 000 до сетевого обрыва на ~177-й странице; повторный resumable-заход: ещё 13 940, `--create-missing` идемпотентен). Без kp_id пропущено 1 953, без года — 70, ошибок API — 0. Все записи созданы DRAFT; на сайте по-прежнему опубликована 1 карточка.
- `player_id` заполняется прямо в массовом импорте из embed_code — отдельный `--full` практически не нужен после `--create-missing` (29 940/29 941).
- Троттлинг Vibix в пике: страница отвечает до ~14 с; полный обход (320 страниц) занимает десятки минут. Ретраи с экспоненциальной паузой отрабатывают, но сетевой обрыв всё равно возможен — импорт перезапускается без потерь.
- **Серии сериалов**: все 7 227 сериалов имеют kp_id. `sync_vibix --episodes` ходит в detail-эндпоинт per-сериал (~2.7 с/сериал → полный проход ~4-5 ч). Идемпотентен: пары «сезон+серия» не дублируются, повторный запуск безопасен. Валидация на 20 сериалах: создано 229 серий, 0 ошибок. Полный прогон запущен 2026-09-06 ~14:36 (PID 26756, лог episodes_full.out, прогресс по `select count(*) from catalog_episode`).

### Session 2026-08-24 — Массовый импорт каталога
- Реализован `sync_vibix --create-missing` (см. Recent Changes) по утверждённому плану: без второй архитектуры, расширение существующего sync-слоя.
- Миграция `0026_title_poster_urls_kp_uniq_import_lock`: poster_url/backdrop_url у Title, locked_at у VideoServiceSyncState, RunPython-дедупликация kp_id перед частичным unique-индексом.
- Общий модуль `apps/catalog/translit.py` (кириллица→латиница), используется import_titles и массовым импортом.
- Урок: `IntegrityError` после успешного `bulk_create` внутри общего savepoint приводил к ложному учёту «created как skipped» — вставка записей и связка жанров/стран разделены по транзакциям; регрессионный тест добавлен.
- Урок: SQLite не умеет case-insensitive сравнение кириллицы (`iexact`) — в dev возможны регистровые дубли справочников жанров/стран; на проде PostgreSQL работает корректно.
- Живая проверка: `check_vibix` все OK; dry-run и реальный импорт страниц каталога прошли, повторный запуск создаёт 0.

### Session 2026-08-21 — Командный запуск
- **SELinux fix**: добавлен суффикс `:z` к volume mounts в `docker-compose.yml` для совместимости с rootless Podman на Fedora (SELinux Enforcing). Без `:z` entrypoint.sh не читается контейнером.
- **start.sh**: добавлена поддержка Podman как fallback для Docker, исправлена генерация `$ADMINPASS`.
- **AGENTS.md**: добавлен раздел `Team Setup` с инструкциями запуска для команды.
- Локальный запуск через `env -i` + nohup работает, но для команды рекомендуется `podman-compose up --build -d`.
