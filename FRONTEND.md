# Контракт вёрстки и поведения

Скрипты проекта находят элементы двумя способами: по `data-*` и по классам.
Разница принципиальная: сломанный `data-*` заметен сразу, сломанный класс — нет.
Переименуйте класс из этого файла при правке стилей, и механика выключится
молча: ни ошибки в консоли, ни красного теста.

Правило: **при правке оформления классы из раздела «Несущие классы» не
переименовывать.** Если переименование всё-таки нужно — правьте JS в том же
коммите и обновляйте этот файл.

## Несущие классы

Скрипт ищет элемент по классу оформления. Самые дорогие — сверху.

| Класс | Кто читает | Что отвалится |
|---|---|---|
| `.search-wrapper` | `app.js` | подсказки поиска перестанут закрываться по клику мимо |
| `.search__suggestion` | `app.js` | стрелки в подсказках |
| `.carousel`, `.carousel__track`, `.carousel__btn--prev/--next` | `app.js` | карусель и свайп |
| `.site-header` | `app.js` | позиция выдвижного меню, тень шапки при прокрутке |
| `.card`, `.card__placeholder`, `.card__name` | `app.js` | градиенты постеров-заглушек |
| `.collection-card__fallback` | `app.js` | то же для подборок |
| `.bottom-nav`, `.bottom-nav__link` | `app.js` | подсветка текущего раздела |
| `.button` | `app.js` | ripple при нажатии |
| `.actor-search__form-wrapper` | `actor-search.js` | закрытие подсказок по клику мимо |
| `#cookie-consent`, `.cookie-consent__accept` | `analytics.js` | баннер согласия не покажется, аналитика не подключится |

## Классы-состояния

Их скрипт и ставит, и **читает** — то есть класс здесь работает как хранилище
состояния. Переименование ломает не вид, а логику.

`mobile-nav--open` · `hamburger--active` · `nav-open` (на `<html>`) ·
`search-open` (на `<html>`) · `search__dropdown--open` · `lightbox--open` ·
`tab--active` · `tab-content--active` · `player-episode--active` ·
`player-voices__item--active` · `player-tabs__tab--active` ·
`lb-xsort-div--open` · `button--active` · `site-header--scrolled` ·
`scroll-top--visible` · `cookie-consent--visible`

## Классы, которых нет в шаблонах

Разметку создаёт скрипт, поэтому поиск «неиспользуемых классов» по шаблонам
покажет их мёртвыми. Они живые:

`search__suggestion*` (`app.js`) · `search__no-results` · `actor-search__suggestion*`
(`actor-search.js`) · `toast`, `toast--success/--error/--info`, `toast__icon`,
`toast__message`, `toast__close` (`app.js`) · `scroll-top` (`app.js`)

Имена, собираемые в шаблоне из переменной, — там же: `message--{{ tags }}`
(`base.html`), `ad-rail--{{ side }}` (`ad_rail.html`),
`award-item__result--{{ … }}` (`person_detail.html`).

## Структурные зависимости

Не класс, но сломается так же тихо.

- `[data-tab-content]` обязан быть **соседом** `[data-tabs]`: `app.js` ищет панели
  в родителе контейнера вкладок. Обернёте вкладки в лишний `<div>` — переключение
  перестанет находить содержимое.
- `[data-player-pane]` ищется **по всему документу**, а не внутри секции плеера.
  Две секции с плеером на одной странице начнут переключать друг друга.
- `[data-title-slug]` берётся первый в документе; на странице фильма их два.
- Форма ответа на комментарий ищет `textarea` **по тегу** — смена виджета формы
  оставит ответ без фокуса в поле.

## Данные из разметки в скрипты

| Источник | Кто читает | Зачем |
|---|---|---|
| `<body data-authenticated>` | `title-detail.js` | гость не шлёт запрос сохранения прогресса, на который сервер ответит 403 |
| `<body data-ui-close>`, `data-ui-scroll-top` | `app.js` | подписи для элементов, которые создаёт скрипт; перевод делает шаблон |
| `meta[name="csrf-token"]` | `title-detail.js` | без него все POST получат 403 |
| `#playback-data` (`json_script`) | `title-detail.js` | матрица «серия × озвучка» |
| `window.lbGaId` | `analytics.js` | без него аналитика не подключается вовсе |
| `localStorage['lumibox-theme']` | `base.html` (инлайн) и `app.js` | общий ключ; расхождение вернёт вспышку тёмной темы |

## Адреса, зашитые в JS

Собираются строкой, `{% url %}` не используется — смена маршрута даст тихий 404:
`/api/v1/titles/search/`, `/api/v1/titles/<slug>/rate/`, `/api/v1/titles/<slug>/watch/`.

## Порядок подключения

`analytics.js` → `favorite.js` → `app.js`, все с `defer`.
`favorite.js` вызывает `window.showToast`, который объявлен в `app.js`, —
зависимость неявная и проверяется через `typeof`. Переставите теги местами —
уведомления об избранном молча исчезнут.
