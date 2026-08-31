О# Архитектура интеграции LumiBox с Vibix

Актуально на 20 августа 2026 года. Документ фиксирует исследованную публичную
экосистему Vibix, контракт OpenAPI 1.1.0 и границы безопасной реализации в
LumiBox. Секреты, логины и пароли здесь не хранятся.

## 1. Карта публичной экосистемы

Vibix нельзя описывать одним доменом. Для интеграции были проверены следующие
публичные контуры.

| Контур | Назначение | Использование LumiBox |
|---|---|---|
| `https://vibix.tv/` | Маркетинговый сайт и контакты партнёрской программы | Нет runtime-зависимости |
| `https://vibix.org/` | Production-кабинет партнёра, hash-routes login/forgot-password | Ручное управление аккаунтом |
| `https://dev.vibix.org/` | Dev/альтернативный кабинет и roadmap | Не использовать в production |
| `https://api.vibix.org/` | Выделенный production API, Swagger, login/register | Default серверного API |
| `https://dev.api.vibix.org/` | Dev API с публично включённым Laravel Debugbar | Запрещён для production |
| `https://plugins.vibix.org/` | Production-сайт DLE-плагина | LumiBox не использует DLE |
| `https://dev.plugins.vibix.org/` | Dev-контур DLE-плагина | Не используется |
| `https://static.vibix.org/` | Статический host без публичного root-контракта | Не используется напрямую |
| `https://demo.vibix.org/` | Сейчас не является рабочим demo-контрактом | Не используется |
| `https://graphicslab.io/sdk/v2/rendex-sdk.min.js` | Mutable SDK браузерного плеера | Глобально в `<head>` из `base.html` (`async`); трафик только на страницах сайта |
| `https://*.kinescopecdn.net` | Текущий iframe/CDN-контур SDK | Разрешён в CSP для frame/connect |
| `https://*.videoframe2.com` | Прежний/вспомогательный iframe-контур | Разрешён в CSP для frame/connect |
| `https://sync.videoframe2.com/` | WatchParty script/WebSocket | Не подключён |
| `https://v-js-menu.run/` и связанные Playmatic hosts | Рекламный loader/VAST | Не входит в ядро, выключен |

Произвольные `*.vibix.tv` нельзя считать отдельными официальными сервисами:
DNS ведёт многие имена на catch-all Tilda «Domain has been assigned».
Certificate Transparency и общий IP сами по себе не доказывают назначение
сервиса или юридическое владение.

### Почему API default — `api.vibix.org`

Одинаковая OpenAPI 1.1.0 доступна и на `vibix.org/api/...`, и на
`api.vibix.org/api/...`. В качестве default выбран выделенный production host:

```text
https://api.vibix.org/api/v1
```

У него собственные Swagger/login/register и корректная host-relative схема.
Прокси на `vibix.org` остаётся наблюдаемым альтернативным контуром, но не
используется по умолчанию. `VIBIX_API_BASE_URL` допускает явное
переопределение, если Vibix выдаст аккаунту иной production endpoint.
Окончательная account-specific проверка выполняется только новым токеном,
заданным непосредственно в секретах окружения.

## 2. OpenAPI 1.1.0

Документация:

- Swagger: `https://api.vibix.org/api/external/documentation`;
- JSON: `https://api.vibix.org/api/external/docs/external-api-docs.json`;
- OpenAPI 3.0, `Vibix API Documentation 1.1.0`;
- Bearer authentication / Laravel Sanctum.

### Publisher endpoints

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/publisher/statistics` | Статистика паблишера |
| GET | `/publisher/videos/kp/{kpId}` | Карточка по Kinopoisk ID |
| GET | `/publisher/videos/imdb/{imdbId}` | Карточка по IMDb ID |
| POST | `/publisher/videos/search` | Поиск |
| GET | `/publisher/videos/links` | Пагинированный каталог |
| GET | `/publisher/videos/get_kpids` | Компактный список KP ID |
| GET | `/publisher/videos/categories` | Категории |
| GET | `/publisher/videos/genres` | Жанры |
| GET | `/publisher/videos/countries` | Страны |
| GET | `/publisher/videos/tags` | Теги |
| GET | `/publisher/videos/voiceovers` | Озвучки |
| GET | `/publisher/videos/occupations` | Профессии |
| GET | `/publisher/get_id` | ID текущего паблишера |

### Serial endpoints

```text
GET /serials/kp/{kpId}
GET /serials/imdb/{imdbId}
```

У serial paths намеренно нет сегмента `/publisher`. Ответ содержит `id`,
`name`, `seasons`; у сезона — `name` и `series`, у серии — `id` и `name`.
`seasons` может быть `null`.

### Форма данных

`/videos/links` возвращает оболочку `{success, data, links, meta}`. Detail
возвращает `VideoLinkResource` напрямую. Существенные поля ресурса:

- `id`, `name`, `name_rus`, `name_eng`, `name_original`;
- `type: movie|serial`, `year`, `kp_id`, `imdb_id`;
- `iframe_url`, `embed_code`;
- ratings/votes, persons, voiceovers, tags;
- poster/backdrop, duration, quality, genre/country;
- descriptions, `uploaded_at` и deprecated `updated_at`.

OpenAPI не объявляет достоверного `licensed`/`playable`. Наличие
`embed_code` доказывает существование embed-кода, но не гарантирует право или
фактическую возможность просмотра для конкретного домена/договора. Поэтому
LumiBox не выдаёт предположение за «серверную проверку лицензии».

## 3. Серверный API-клиент

Файл: `apps/catalog/video_service_api.py`.

- токен берётся из `VIBIX_API_TOKEN` (старое `VIDEO_SERVICE_API_KEY` — fallback);
- заголовки: `Authorization: Bearer ...` и `Accept: application/json`;
- redirects отключены, чтобы redirect на HTML login не превратился в ложный 404;
- connect/read timeout: 5/30 секунд;
- `429`, `500`, `502`, `503`, `504` и network errors получают ограниченный retry;
- `Retry-After` уважается, иначе применяется exponential backoff;
- `401`, `403`, `404`, `422`, non-JSON и JSON не в форме объекта различаются;
- KP ID допускает только цифры, IMDb — `tt` + цифры;
- токен не попадает в URL, HTML и сообщения об ошибках.

`requests` закреплён как прямая production-зависимость. Раньше он приезжал
только транзитивно через dev/Selenium, из-за чего production worker и команды
Vibix могли не импортироваться.

## 4. Сопоставление и синхронизация

### Модель

`Title` хранит:

- `kp_id`;
- `imdb_id`;
- `player_id` — только `data-id`, извлечённый из `embed_code`;
- `player_type` — `movie` или `series`.

`VideoLinkResource.id` не используется как `player_id`: OpenAPI не обещает,
что ID API-ресурса равен ID browser embed.

`VoiceOver.vibix_voiceover_id` связывает локальную озвучку со справочником
Vibix. `VideoServiceSyncState.last_updated_from` хранит watermark массового
синка.

### Matching

Приоритет сопоставления:

1. точный KP ID;
2. точный нормализованный IMDb ID;
3. единственное совпадение названия и года.

Неоднозначное совпадение пропускается. Ручные значения не затираются.
Синхронизация также может заполнить пустые description, short description,
original name, duration, KP/IMDb ratings, genres и countries.

Watermark фиксируется до обхода страниц и сохраняется только после успешного
завершения. Изменение во время долгого sync попадёт в следующий запуск.
`--dry-run` не пишет ни каталог, ни состояние.

### Сериалы

`sync_vibix --episodes` обходит только записи типа `series` с KP/IMDb ID.
Он не ограничивается сериалами без эпизодов: существующие пары сезон/серия
пропускаются, а новый сезон добавляется. Фильмы никогда не отправляются на
serial endpoint.

## 5. Браузерный плеер

Страница не обращается к серверному API Vibix. Приоритет публичного embed:

1. numeric `player_id` + `movie|series`;
2. numeric `kp_id` с типом `kp`;
3. IMDb `tt...` с типом `imdb`.

Publisher ID обязан быть числовым. Design ограничен `1..6`, trailer —
`true|only`. Для прямого series embed передаются season/episode; сопоставленная
озвучка передаётся `data-voiceover`.

### Lazy loading и privacy boundary

Rendex SDK подключён глобально в `<head>` из `base.html` (`async`): контракт
плеера требует скрипт на странице до инициализации `<ins>`. Видео при этом
не предзагружается — `data-nopreload="true"` и `data-poster="true"` в партиале
`templates/includes/player.html` откладывают запросы до действия зрителя.
Gate с кнопкой «Начать» рендерит только `<ins>` с публичными ID и локальный
`static/js/vibix-player.js`. После кнопки загрузчик:

1. убеждается, что Rendex SDK уже в `<head>` (он подключён глобально из base.html);
2. наблюдает за заменой `<ins>` на iframe;
3. показывает loading/error state с 20-секундным timeout;
4. не передаёт `VIBIX_API_TOKEN` браузеру;
5. корректно сохраняет выбранную до запуска серию в `data-season` и
   `data-episodes`.

Это важно, потому что SDK обфусцирован и изменяется по неизменному URL. В
публичных сборках наблюдались разные digests и iframe-инфраструктура
`*.kinescopecdn.net` / `*.videoframe2.com`. SRI на mutable URL использовать
нельзя без фиксации конкретного разрешённого артефакта; вместо ложной
гарантии применяется явное действие пользователя, строгая CSP и timeout UX.

CSP разрешает SDK с `graphicslab.io` и iframe/connect только с известных
контуров `*.kinescopecdn.net` и `*.videoframe2.com`. Media уже разрешено по
HTTPS для существующих видеоисточников сайта.

## 6. Команды

```bash
# Инкрементальный каталог
python manage.py sync_vibix

# Полный каталог / проверка без записи
python manage.py sync_vibix --full
python manage.py sync_vibix --dry-run

# Одна запись с уже заполненным KP/IMDb
python manage.py sync_vibix --title <slug>

# Озвучки / новые сезоны и серии
python manage.py sync_vibix --voiceovers
python manage.py sync_vibix --episodes
python manage.py sync_vibix --episodes --limit 10 --dry-run

# Создать НОВЫЕ записи по списку Kinopoisk ID (метаданные из API)
python manage.py create_from_vibix 447301 258687 361
python manage.py create_from_vibix --file kp_ids.txt
python manage.py create_from_vibix 447301 --dry-run

# Массовый импорт всего каталога издателя (наполнение с нуля)
python manage.py sync_vibix --create-missing --dry-run          # план без записи
python manage.py sync_vibix --create-missing                    # все, черновики
python manage.py sync_vibix --create-missing --type serial      # только сериалы
python manage.py sync_vibix --create-missing --type movie       # потом фильмы
python manage.py sync_vibix --create-missing --status published # сразу опубликовать
python manage.py sync_vibix --unlock                            # снять зависший лок
```

`sync_vibix` обогащает уже существующие записи (совпадение по названию и
году), `create_from_vibix` — заводит новые по точному Kinopoisk ID: название,
год, imdb_id, player_id, описание, рейтинги, длительность, жанры и страны.
Идемпотентна: ID с уже существующей записью пропускается.

### Массовый импорт (--create-missing)

Обходит весь список издателя `GET /publisher/videos/links` и создаёт записи,
которых ещё нет. Ключевые свойства:

- **Дедуп по kp_id**: перед запуском снимок существующих ID одним запросом;
  повторный прогон после обрыва продолжает с места остановки. Дубль
  невозможен и на уровне БД — частичный уникальный индекс
  `title_kp_id_uniq_when_filled` (миграция 0026).
- **Карточки без kp_id пропускаются** (счётчик no_kp_id в отчёте): без
  внешнего ID невозможен ни дедуп, ни сопоставление серий.
- **Батчи по `--batch-size`** (по умолчанию 500) через bulk_create, связи
  с жанрами/странами — массово через through-таблицу; коммит на батч.
- **Параллельные прогоны** отсекаются блокировкой строки в
  `VideoServiceSyncState` (ключ `bulk-import`, протухает через 12 ч,
  снимается `--unlock`).
- **Новые записи — черновики** (`--status published` публикует сразу);
  постеры не скачиваются: адреса сохраняются в `poster_url`/`backdrop_url`.
- **Память O(1)**: каталог читается генератором постранично, состояние —
  три множества ID/слагов на весь прогон.
- Серии сериалов тянутся вторым этапом: `sync_vibix --episodes`.

Celery-задача `create_missing_catalog` дублирует команду для запуска через
воркер (в расписание не внесена).

Старые `sync_video_service`, `sync_voiceovers`, `sync_episodes` оставлены для
совместимости и вызывают то же ядро. В админке есть действия sync/dry-run для
выбранных записей. Celery раз в сутки делает incremental catalog и voiceover
sync; без токена задачи безопасно пропускаются.

## 7. Production rollout

1. Ротировать любой токен, который когда-либо попадал в Git.
2. Задать новый `VIBIX_API_TOKEN` только в secrets хостинга.
3. Задать publisher ID, выданный кабинетом, и зарегистрировать production domain.
4. Выполнить `sync_vibix --dry-run`, затем точечный `--title`.
5. Выполнить `--voiceovers` и `--episodes --limit 10 --dry-run`.
6. На approved domain снять browser network trace: SDK, iframe origin,
   XHR/media, postMessage и CSP violations.
7. Только после проверки запустить полный/реальный sync.

Без нового легитимного токена нельзя подтвердить account-specific каталог,
`embed_code`, договорную доступность и регистрацию домена. Старое значение из
Git history использовать нельзя.

## 8. Что намеренно не включено

### WatchParty

Публичная библиотека использует `wss://sync.videoframe2.com`, room ID из URL
и postMessage-команды. В исследованной версии команды отправлялись с target
`*`, а входящие сообщения не имели явного origin allowlist. Поэтому runtime
код и настройка WatchParty удалены из базового продукта. Возврат возможен
только после отдельного origin/auth/privacy/browser review.

### Рекламная сеть

Loader `v-js-menu.run` загружает Playmatic-контур и поддерживает preroll,
stickers, banners, branding, flyroll, clickunder/popunder и другие форматы.
Исследованный код собирает canvas/audio/WebGL/WebRTC/fonts/plugins/permissions/
hardware fingerprint, добавляет `fp` в tracking и может исполнять внешние
VAST/VPAID/HTML/JS creatives. `ADS_NETWORK_ENABLED` остаётся `False` по
умолчанию и не включается интеграцией плеера. Согласие на Google Analytics
для этой сети недостаточно: нужны отдельные consent, privacy policy, legal,
isolation и CSP решения.

### Dev/debug и DLE

`dev.api.vibix.org` раскрывает Debugbar, PHP/internal paths, routes и SQL —
его нельзя использовать в production и не нужно исследовать закрытые debug
endpoints. Публичный DLE package сейчас не подтверждён доступным без кабинета;
LumiBox реализует native Django integration и не зависит от плагина.
