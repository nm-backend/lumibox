# Архитектура LumiBox: интеграция Vibix API, плеер и синхронизация

> Сводный документ по результатам изучения кода проекта LumiBox.
> Цель — полное понимание архитектуры, интеграции Vibix API, плеера
> и синхронизации. Никаких изменений кода не вносится.

> 📄 **Смежный документ:** [VIBIX_INSTRUCTIONS.md](VIBIX_INSTRUCTIONS.md) —
> перевод официальной инструкции Vibix (эндпоинты API, плеер, data-design,
> реклама, WatchParty, микроразметка).

## 1. Обзор проекта

**LumiBox** — кинопортал на Django 5.x с каталогом фильмов/сериалов, поиском,
фильтрами, личной библиотекой, отзывами, обсуждениями, REST API (DRF +
drf-spectacular) и админкой. Собственный дизайн (светлая/тёмная тема),
адаптивная вёрстка, чистый CSS и ванильный JavaScript без сборки.

**Технологический стек:**
- Python 3.12+ / Django 5.x / PostgreSQL 17+ (production)
- Redis + Celery (опционально — фоновые задачи)
- `requests` для внешних запросов (Vibix API)
- Vanilla JS — `player.js`, `title-detail.js`, `watch-party.js`
- SDK Vibix: `https://graphicslab.io/sdk/v2/rendex-sdk.min.js`

**Метрики качества (из AUDIT.md):** 477 тестов (3 skip), покрытие 95%
(порог CI 90%), ruff 0 ошибок, mypy 0 ошибок (113 файлов), CI зелёный
на PostgreSQL 18 + Redis 8.

## 2. Архитектура приложения

```
apps/
├── catalog/    # Title, Episode, Genre, Country, PlaybackSource, ...
├── core/       # Общие модели, тест-фабрики, middleware
├── api/        # DRF API + drf-spectacular схемы
├── library/    # Избранное, «смотреть позже», история
├── reviews/    # Оценки и комментарии
└── users/      # Пользователь, регистрация, профиль
```

Модели каталога живут в пакете `apps/catalog/models/`.
Все собираются в `models/__init__.py`.

### Ключевые модели

| Модель | Файл | Кратко |
|---|---|---|
| `Title` | `models/title.py` | Фильм/сериал (одна модель на оба типа) |
| `Episode` | `models/episode.py` | Серия сериала |
| `PlaybackSource` | `models/playback.py` | Источник: файл или embed |
| `VoiceOver` | `models/reference.py` | Справочник озвучек |
| `VideoServiceSyncState` | `models/video_service.py` | Состояние синхронизации (singleton) |

### Ключевые поля модели Title

```python
# apps/catalog/models/title.py
class Title(SeoModel, TimeStampedModel):
    type = ...              # movie | series | cartoon | tv_show
    name = ...              # Русское название
    original_name = ...     # Оригинальное название
    slug = ...              # URL-адрес
    release_year = ...      # Год выпуска (обязательно)

    # ── Поля плеера Vibix ──
    kp_id = ...      # ID Кинопоиска (например 326 — Шоошенк)
    imdb_id = ...    # ID IMDb (например tt0111161)
    player_id = ...  # Внутренний ID видео в Vibix (data-id тега)
    player_type = ...# movie | series (data-type тега)

    # ── YouTube ──
    video_url = ...     # YouTube ссылка на полную версию
    trailer_url = ...   # YouTube ссылка на трейлер
```

### PlaybackSource

- `Kind.FILE` — локальный файл (отдаётся через Range 206/416)
- `Kind.EMBED` — внешний плеер (URL проходит валидацию `embeds.get_embed_url()`
  по белому списку: YouTube, Vimeo, Rutube)
- Свойство `src` — вычисляет embed-адрес через `get_embed_url()`

### VideoServiceSyncState (singleton)

```python
key = "default"
last_updated_from = DateTimeField  # для инкрементального синка
updated_at = DateTimeField(auto_now=True)
```

### Другие приложения

| Приложение | Модели | Роль |
|---|---|---|
| `apps/library` | `Favorite`, `WatchHistory`, `Watchlist` | Связи пользователь↔запись: избранное, история (с позицией в секундах), «смотреть позже» |
| `apps/reviews` | `Review`, `Comment` | Отзывы (1 на пользователя, 1–10) + комментарии (вложенность ровно 2 уровня) |
| `apps/api` | DRF v1 | ViewSet'ы `titles`, `genres`, `countries`, `collections` + вложенные `reviews`/`comments`, `rate`, `watch` |
| `apps/core` | `SeoModel`, `TimeStampedModel` | Абстрактные основы, middleware (CSP, RequestId), контекст-процессоры |


---

## 3. Player rendering flow

### 3.1 Конвейер рендеринга

```
TitleDetailView.get()
  └─> _get_external_player()  → словарь с параметрами плеера
  └─> get_context_data()      → контекст для шаблона
  └─> шаблон title_detail.html
  └─> <ins data-publisher-id=... data-type=... data-id=...>
  └─> браузер: rendex-sdk.min.js → заменяет <ins> на <iframe>
  └─> Vibix iframe плеер
```

### 3.2 TitleDetailView._get_external_player()

Файл: `apps/catalog/views.py`, строки 584–640.

Собирает словарь с параметрами для тега `<ins>`:

1. **publisher_id** — из `settings.VIBIX_PUBLISHER_ID` (678503345).
   Пустой publisher_id → `None` → вкладка плеера не рендерится, SDK не грузится.
2. **design** — из `settings.VIDEO_SERVICE_DESIGN` (default "1").
3. **colors** — `VIDEO_SERVICE_COLOR1..5` (палитра: #ff8a1f, #ffffff,
   #ffb057, #e06d00, #0b0b0c). Пустые цвета выпиливают `data-colorN`.
4. **type и id** — по приоритету:
   - `player_id` заполнен → `data-type=player_type` (movie/series),
     `data-id=player_id`. **Официальный формат эмбеда**.
   - `kp_id` → `data-type="kp"`, `data-id=kp_id` (browser-side резолвинг, без токена).
   - `imdb_id` → `data-type="imdb"`, `data-id=imdb_id`.

Для сериалов дополнительно: `season`/`episodes` из `_opening_episode()`,
`data-voiceover` из `_external_voiceover_ids()`.

### 3.1 Конвейер рендеринга

```
TitleDetailView.get()
  └─> _get_external_player()  → словарь с параметрами плеера
  └─> get_context_data()      → контекст для шаблона
  └─> шаблон title_detail.html
  └─> <ins data-publisher-id=... data-type=... data-id=...>
  └─> браузер: rendex-sdk.min.js → заменяет <ins> на <iframe>
  └─> Vibix iframe плеер
```

### 3.2 TitleDetailView._get_external_player()

Файл: `apps/catalog/views.py`, строки 584–640.

Собирает словарь с параметрами для тега `<ins>`:

1. **publisher_id** — из `settings.VIBIX_PUBLISHER_ID` (default 678503345).
   Пустой publisher_id → `None` → вкладка плеера не рендерится, SDK не грузится.
2. **design** — из `settings.VIDEO_SERVICE_DESIGN` (default "1").
3. **colors** — `VIDEO_SERVICE_COLOR1..5` (палитра: #ff8a1f, #ffffff,
   #ffb057, #e06d00, #0b0b0c). Пустые цвета выпиливают `data-colorN`.
4. **type и id** — по приоритету:
   - `player_id` заполнен → `data-type=player_type` (movie/series),
     `data-id=player_id`. **Официальный формат эмбеда** («Код» в кабинете Vibix).
   - `kp_id` → `data-type="kp"`, `data-id=kp_id` (browser-side резолвинг, без токена).
   - `imdb_id` → `data-type="imdb"`, `data-id=imdb_id`.

Для сериалов дополнительно: `season`/`episodes` из `_opening_episode()`,
`data-voiceover` из `_external_voiceover_ids()`.

**data-design (1–6):** `VIDEO_SERVICE_DESIGN` (из `base.py`, default "1").
| Значение | Описание |
|---|---|
| 1 | По умолчанию |
| 2 | Монохром |
| 3 | Синий Неон |
| 4 | Ютуб |
| 5 | Ночной Минимализм |
| 6 | Карусель эпизодов |

### 3.3 Опции плеера

| Параметр | Настройка | Значение |
|---|---|---|
| `data-trailer` | `VIDEO_SERVICE_TRAILER` | `true` / `only` / пусто |
| `data-autoplay` | `VIDEO_SERVICE_AUTOPLAY` | False (по умолчанию) |
| `data-sync` | `VIDEO_SERVICE_WATCH_PARTY` | False (по умолчанию) |

**Важно:** если `external_player` настроен → YouTube плеер НЕ показывается
(шаблон: `{% if has_playback and not external_player %}`).

### 3.4 Шаблон (title_detail.html, строки 563–585)

Тег `<ins>` рендерится с атрибутами из словаря `external_player`:
`data-publisher-id`, `data-type`, `data-id`, `data-design`, `data-colorN`,
`data-trailer`, `data-season`, `data-episodes`, `data-voiceover`,
`data-voiceover-only`, `data-autoplay`, `data-sync`.

### 3.5 Client-side JS

**`player.js`** — кастомные контролы для `<video>` (файлы).
Для iframe-плееров ничего не делает.

**`title-detail.js`** — переключение серий/озвучек, оценка звёздами,
модальный трейлер. Ключевая функция для Vibix (строки 389–406):

```javascript
// SDK заменяет <ins> на iframe при старте — новые теги не подхватывает.
// Поэтому адрес iframe переписывается напрямую:
function updateExternalPlayer(season, episode) {
    var pane = document.querySelector('[data-player-pane="external"]');
    var frame = pane ? pane.querySelector('iframe') : null;
    if (!frame || !season || !episode) return;
    var url = new URL(frame.src, window.location.href);
    url.searchParams.set('season', String(season));
    url.searchParams.set('episode[]', String(episode));
    frame.src = url.toString();
}
```

**`watch-party.js`** — WatchParty через `sync.videoframe2.com/sync-lib.js`.

---

## 4. Vibix API integration

### 4.1 Настройки (.env.example)

```dotenv
VIBIX_PUBLISHER_ID=678503345
VIBIX_API_TOKEN=29756|4yaXH5dIT0A2EtB27D55qUlYmfc28MzM3875wtj4800a4f63
VIBIX_API_BASE_URL=https://api.vibix.org/api/v1
VIDEO_SERVICE_DESIGN=1
VIDEO_SERVICE_COLOR1..5=#ff8a1f #ffffff #ffb057 #e06d00 #0b0b0c
VIDEO_SERVICE_TRAILER=true
VIDEO_SERVICE_AUTOPLAY=False
VIDEO_SERVICE_WATCH_PARTY=False
```

**Разные базы API в конфигах:**
| Файл | Значение | Статус |
|---|---|---|
| `.env` (рабочий dev) | `https://api.vibix.org/api/v1` | ❌ Неверный домен |
| `.env.example` | `https://api.vibix.org/api/v1` | ❌ Неверный домен |
| `base.py` (default) | `https://api.vibix.org/api/v1` | ❌ Неверный домен |
| `render.yaml` | `https://vibix.org/api/v1` | ✅ Правильно |
| `render.paid.yaml` | `https://vibix.org/api/v1` | ✅ Правильно |
| `development.py` | наследует default base.py | ❌ → `api.vibix.org` |
| `production.py` | наследует default base.py | ❌ → `api.vibix.org` |

**Учётные данные для session auth:** `VIBIX_USERNAME=fleecemaster40k@gmail.com`,
`VIBIX_PASSWORD=0NApy_2eFwom` (присутствуют в `.env`, для `scripts/vibix_session_test.py`).

### 4.2 Клиент API (video_service_api.py)

```python
# База с /publisher префиксом (видео)
VIDEO_SERVICE_API_BASE = f"{settings.VIBIX_API_BASE_URL.rstrip('/')}/publisher"

# База без /publisher (сериалы — отдельный хост!)
VIDEO_SERVICE_SERIALS_API_BASE = settings.VIBIX_API_BASE_URL.rstrip("/")
```

**Auth:** `Authorization: Bearer {token}` из `get_vibix_api_token()`
(читает `VIBIX_API_TOKEN` или fallback `VIDEO_SERVICE_API_KEY`).

**Retries:** `MAX_RETRIES=6`, экспоненциальная задержка, уважение `Retry-After`,
`PAGE_DELAY=0.35s` между страницами.

### 4.3 Эндпоинты

| Метод | Путь | Функция | Описание |
|---|---|---|---|
| GET | `/publisher/videos/links` | `fetch_video_links()` | Список видео (`{success, data, meta}`) |
| GET | `/publisher/videos/kp/{id}` | `fetch_video_by_kp()` | Карточка по Kinopoisk ID |
| GET | `/publisher/videos/imdb/{id}` | `fetch_video_by_imdb()` | Карточка по IMDb ID |
| GET | `/serials/kp/{id}` | `fetch_serial_by_kp()` | Сезоны/серии (БЕЗ /publisher!) |
| GET | `/serials/imdb/{id}` | `fetch_serial_by_imdb()` | Сезоны/серии (БЕЗ /publisher!) |
| GET | `/publisher/videos/get_kpids` | `fetch_video_kpids()` | Список KP IDs |
| GET | `/publisher/videos/voiceovers` | `fetch_voiceovers()` | Список озвучек |
| GET | `/publisher/videos/categories` | `fetch_categories()` | Категории |
| GET | `/publisher/videos/genres` | `fetch_genres()` | Жанры |
| GET | `/publisher/videos/countries` | `fetch_countries()` | Страны |
| GET | `/publisher/videos/tags` | `fetch_tags()` | Теги |

**Важно:** серийные эндпоинты (`/serials/...`) работают **без** `/publisher`
префикса. Запросы на `/api/v1/publisher/serials/...` возвращают 404.

### 4.4 Рекламная сеть Vibix (реализована)

Настройки в `base.py`: `ADS_NETWORK_ENABLED` (default False),
`ADS_NETWORK_PUBLISHER_ID` (default `678503345`),
`ADS_NETWORK_ADD_TYPES` (default `"sticker,pcsticker,banners"`).

**Реализация:**
- `apps/core/context_processors.py` — `ads_network` в контексте
  (`enabled`, `publisher_id`, `add_types`).
- `apps/core/middleware.py` — `ADS_NETWORK_CSP_ADDITIONS` расширяют CSP
  на домены `v-js-menu.run`, `cdn.timing-js-menu.xyz`, `vast2.ufouxbwn.com`,
  `cdn7.ufouxbwn.com` (креативы и iframe приходят с произвольных https-доменов).
- `templates/base.html` — лоадер `https://v-js-menu.run/public/lib.en.min.js`
  + `<ins id="vibix_union" data-publisher_id="..." data-add_types="...">`.
  id фиксированный — его жёстко ищет внешний скрипт-лоадер.
- `templates/includes/ad_slot.html` — слот 728×90 `<ins data-pm-b="...">`,
  движок находит его по `data-pm-b`.

Форматы `data-add_types`: `sticker`, `pcsticker`, `banners`, `brand`, `flyroll`.
`brand` выключен по умолчанию (подстраивает сайт под креатив и может сломать
вёрстку); `flyroll` — рекламный ролик, подключается по желанию.

### 4.5 Микроразметка Vibix (НЕ реализована)

Официальная инструкция Vibix рекомендует поля DLE `vibix_schema_microdata`
(JSON-LD) и `vibix_og_microdata` (Open Graph). В LumiBox эти поля
**отсутствуют** — микроразметка генерируется через `SeoModel`
(`apps/core/models.py`, поля `meta_title`/`meta_description`) и
встроенные теги в `title_detail.html`.


---

## 5. Система синхронизации

### 5.1 Файлы

| Файл | Роль |
|---|---|
| `video_service_sync.py` | `sync_video_service_ids()`, `sync_title()`, `sync_series_episodes()` |
| `video_service_voiceover_sync.py` | `sync_voiceover_ids()`, `import_voiceovers_from_service()` |
| `management/commands/sync_video_service.py` | Массовая синхронизация |
| `management/commands/sync_vibix.py` | Синхронизация одной записи |
| `tasks.py` | Celery задачи (ежедневный запуск) |

### 5.2 sync_video_service_ids() — массовая синхронизация

```
sync_video_service_ids(full=False, dry_run=False)
  └─> VideoServiceSyncState.get_solo()  → last_updated_from
  └─> build_title_index()  → индекс записей с пустыми ID
  └─> _filter_years()  → year[] фильтр (если все записи имеют release_year)
  └─> iter_video_links()  → генератор страниц API
  └─> для каждой записи:
      match_item(index, item) → сопоставление по названию + году
      _embed_player(item) → извлечение player_id из embed_code
      _collect_enrichment() → обогащение описанием, рейтингами, жанрами
```

**Правила:**
1. Заполняются **только пустые поля** (ручная работа не затирается).
2. **Год — стоп-фактор:** если годы не совпадают — пропускаем.
3. Тип (фильм/сериал) не фильтруется.

**Инкрементальность:** `updated_from` передаётся в API, после успешного
запуска обновляется на текущее время.

### 5.3 Ключевая функция _embed_player()

```python
# Внутренний id из списка API НЕ совпадает с data-id плеера!
# (проверено на всех 160 записях — расхождение у каждой)
match = re.search(r'data-id="(\d+)"', item.get("embed_code") or "")
if match:
    return match.group(1), _API_TO_TAG_TYPE.get(item.get("type"))
return str(item.get("id") or ""), _API_TO_TAG_TYPE.get(item.get("type"))

# Маппинг: API "serial" → SDK "series"
_API_TO_TAG_TYPE = {"movie": "movie", "serial": "series"}
```

### 5.4 Озвучки (video_service_voiceover_sync.py)

- `import_voiceovers_from_service()` — импорт новых озвучек из `/videos/voiceovers`
- `sync_voiceover_ids()` — сопоставление `vibix_voiceover_id` по нормализованному названию

### 5.5 match_item()

Сопоставление по названию (русскому, английскому, оригинальному) + году.
Нормализация: `ёлка!` → `ёлка`, `«Ёлки-2»` → `ёлки 2`.

---

## 6. Тесты

### test_player.py
Тесты выбора озвучки, источников и разметки. **Важно:** проверяет, что
API-токен **никогда не попадает в HTML** (assertNotContains для токенов).

### test_video_service_sync.py
Мок HTTP на уровне `requests`. Ключевые тесты:
- `test_does_not_clobber_manual_player_id` — ручной player_id не затирается
- `test_fills_serial_type_mapped_to_series` — mapping serial → series
- `test_dry_run_changes_nothing` — dry-run не пишет в БД
- `test_incremental_uses_stored_updated_from` — инкрементальность
- `MAX_RETRIES` — проверка поведения при 429/5xx

### test_views.py (часть плеера)
- `test_external_player_autoplay_when_enabled`
- `test_external_player_watch_party_when_enabled`
- `test_external_player_trailer_only_mode`
- Тесты используют `player_id="4427"`, `slug="igra-v-kalmara-2021"`

**Метрики:** 477 тестов, 95% покрытие, ruff 0 ошибок, mypy 0 ошибок.

---

## 7. Экспериментальные файлы

### 7.1 vibix-play-test.html — реальные ID

| Фильм | data-type | data-id | Примечание |
|---|---|---|---|
| «Остров возрождения» | movie | 326776 | Из каталога Vibix (13.08.2026) |
| «Интерстеллар» | movie | 4433 | player_id из синка |
| «Игра в кальмара» | series | 222 | Сезон 1, серия 1 |

### 7.2 vibix-probe2.html — 6 вариантов эмбеда

| № | data-type | data-id | Примечание |
|---|---|---|---|
| 1 | kp | 326 | Шоошенк — пример из документации |
| 2 | kp | 447301 | «Начало» — наш вариант (из README) |
| 3 | movie | 187471 | Пример из документации |
| 4 | movie | 4427 | embed_code API для «Начала» |
| 5 | imdb | tt1375666 | «Начало» по IMDb |
| 6 | movie | 199296 | «Остров возрождения» (id из API) |

### 7.3 Скрипты исследования (scripts/)

| Скрипт | Цель |
|---|---|
| `vibix_test_token.py` | Тест Bearer токена на разных эндпоинтах |
| `vibix_session_test.py` | Session-based auth через CSRF cookies |
| `vibix_check.py` | Discovery через session + login на vibix.org |
| `vibix_explore.py` | Полный обход API: видео, озвучки, сериалы |
| `vibix_domains.py` | Тест разных доменов |
| `vibix_browser_explore.py` | Обход API из браузерной сессии |
| `vibix_discover.py`, `vibix_discovery.py` | Discovery эндпоинтов Vibix |
| `vibix_manual_test.py` | Ручной тест API |
| `diagnose_player.py` | Диагностика отрендеренной страницы плеера |
| `update_player_id.py` | **ОШИБОЧНЫЙ** — установил player_id="326" |

### 7.4 Эксперименты диагностики плеера (.freebuff/)

| Файл | Что проверяет |
|---|---|
| `ab-vibix-check.js` | Вкладки плеера, панель vibix (hidden/ins/iframe), размеры iframe |
| `ab-vibix-size.js` | Размеры iframe плеера (rect/inlineStyle/css), первые 120 симв. src |
| `ab-vibix-nosrc.js` | SDK загружен (`window.RendexSDK`), панели player1/vibix, JS-ошибки |
| `ab-vibix-switch.js` | Переключение вкладок: клик по «vibix», создание iframe, размеры |
| `ab-ads-probe.js` | Реклама Vibix Union: лоадер, `vibix_union`, движок `window.isPMLoaded`, баннер-слоты `ins[data-pm-b]`, горизонтальная прокрутка |
| `ab-open-vibix.html` | Открытие страницы с вкладкой Vibix |
| `ab-player.js`, `ab-init.js` | Инициализация и состояние плеера |
| `worktrees/*/ab-*` | Диагностика в отдельном worktree (analyze, errbox, sweep) |

Скриншоты: `vibix-desktop.png`, `vibix-mobile.png`, `vibix-nosrc-*.png`,
`ads-desktop.png`, `ads-mobile.png`, `catalog-desktop.png`, `catalog-mobile.png`.

Дампы БД: `desktop.db`, `desktop-v2.db` (SQLite из экспериментов).

---

## 8. Ключевые проблемы и пробелы

### 8.1 ❌ player_id = "326" — КРИТИЧЕСКАЯ ОШИБКА

**Суть:** В базе запись имеет `player_id="326"`, `player_type="movie"`.

Число **326** — это **kp_id Шоошенка** (Kinopoisk ID), а НЕ внутренний ID
видео в Vibix!

**Доказательство:**
- `scripts/update_player_id.py` (строка 17):
  ```python
  title.player_id = '326'  # Example video ID from Vibix docs
  ```
  Комментарий "Example video ID from Vibix docs" — но 326 взято из
  `vibix-probe2.html` как `data-type="kp" data-id="326"` (Шоошенк по Kinopoisk).

- `vibix-probe2.html` вариант 1:
  ```html
  <ins data-publisher-id="678503345" data-type="kp" data-id="326" ...></ins>
  ```
  Здесь 326 используется с `data-type="kp"`, а **не** с `data-type="movie"`.

**Почему это сломано:**
- `_get_external_player()` выбирает `player_id` с приоритетом:
  ```python
  if self.object.player_id.strip():
      player.update({"type": embed_type, "id": self.object.player_id.strip()})
  ```
- Плеер рендерится как `data-type="movie" data-id="326"`.
- SDK пытается загрузить видео с ID 326 в типе "movie" — но 326 это kp_id,
  а не ID контента в Vibix. Плеер показывает ошибку или чёрный экран.

**Решение:**
- **Вариант A (рекомендуется):** Удалить `player_id="326"` и `player_type="movie"`.
  Тогда `_get_external_player()` переключится на `data-type="kp" data-id="326"` —
  SDK Vibix разрешит этот ID в браузере **без API-токена** (как в README для
  «Начала» с kp_id=447301).

### 8.2 ❓ Vibix API токен не работает

**Симптом:** `Bearer` токен
(`29756|4yaXH5dIT0A2EtB27D55qUlYmfc28MzM3875wtj4800a4f63`)
в `development.py` (через `.env`, база = `api.vibix.org`) при запросе к
`https://api.vibix.org/api/v1/publisher/videos/links`
возвращает **HTML страницу входа** вместо JSON.

**Корневая причина:** `base.py` (default) и `.env.example` используют базовый URL
**`https://api.vibix.org/api/v1`** (с субдоменом `api.`). Согласно официальной
документации Vibix (`https://vibix.org`), правильный базовый URL —
**`https://vibix.org/api/v1`** (**без** `api.`)

- `render.yaml` / `render.paid.yaml` корректно указывают `vibix.org` → работают.
- `base.py` default и `.env` указывают `api.vibix.org` → **это баг**.
- `development.py` наследует default из base.py = `api.vibix.org`.
- **README.md описывает default как `https://vibix.org/api/v1`** — расходится
  с реальным default в `base.py` (`api.vibix.org`). Документация говорит одно,
  код делает другое.

**Решение:**
1. **Код:** изменить `VIBIX_API_BASE_URL` default в `base.py` и `.env.example`
   на `https://vibix.org/api/v1`.
2. **Dev-only быстрее:** в `development.py` переопределить:
   ```python
   VIBIX_API_BASE_URL = "https://vibix.org/api/v1"
   ```
3. **Alt:** session-based auth (scripts/vibix_session_test.py) с учётными
   данными `VIBIX_USERNAME`/`VIBIX_PASSWORD`.

**Что уже пробовали:** скрипты `vibix_test_token.py`, `vibix_session_test.py`,
`vibix_check.py`, `vibix_domains.py` тестировали разные домены и методы auth.

### 8.3 ⚠️ Сериалы используют отдельный API хост

`VIDEO_SERVICE_SERIALS_API_BASE` = `VIBIX_API_BASE_URL` **без** `/publisher`.
Запросы на `/api/v1/publisher/serials/...` возвращают 404.

### 8.4 ⚠️ Fallback на внутренний ID в _embed_player()

Если API уберет поле `embed_code`, `_embed_player()` вернёт `item["id"]` —
внутренний ID записи, который **не является** player_id. Плеер сломается.
Рекомендуется добавить логирование для таких случаев.

---

## 9. Маршруты и команды

### URL каталога (apps/catalog/urls.py)

| URL | View |
|---|---|
| `/` | HomeView |
| `/catalog/` | TitleListView |
| `/title/<slug:slug>/` | **TitleDetailView** |
| `/new/`, `/popular/`, `/top/`, `/premieres/` | Разделы-витрины |
| `/year/<int:year>/` | YearTitleListView |
| `/franchises/<slug:slug>/` | FranchiseDetailView |
| `/search/` | SearchView |
| `/random/` | RandomTitleView |

### Управляющие команды

| Команда | Описание |
|---|---|
| `sync_video_service` | Массовая синхронизация (инкрементально / `--full` / `--dry-run`) |
| `sync_vibix` | Синхронизация одной записи по slug |
| `sync_episodes` | Импорт серий сериалов (`--dry-run`) |
| `sync_voiceovers` | Синхронизация озвучек (`--dry-run`) |

### 9.3 Docker и CI/CD

**Dockerfile** (multi-stage):
- `base` — python:3.13-slim + libpq5 + fonts-dejavu-core (кириллический шрифт для постеров-заглушек)
- `builder` — сборка production-зависимостей
- `development` — все зависимости, runserver 0.0.0.0:8000, код монтируется из compose
- `production` — gunicorn gthread 3 workers / 4 threads / timeout 300, отдельный пользователь `app`, collectstatic в образ

**docker-compose.yml** (локальная разработка):
- `db` — postgres:18-alpine на порту **5433** (локальный 5432 занят)
- `redis` — redis:8-alpine на порту **6380**
- `web` — target development, entrypoint применяет миграции и наполняет каталог
- `docker-compose.prod.yml` — боевое окружение (SECURE_SSL_REDIRECT)

**CI** (`.github/workflows/ci.yml`, на каждый push/PR в main):
1. `ruff check apps config scripts`
2. `mypy apps`
3. `scripts/check_branding.py` (запрет kg-*/kinogo)
4. `python manage.py check`
5. `makemigrations --check --dry-run`
6. `check --deploy --fail-level WARNING` (production settings)
7. `manage.py test apps` + `coverage report --fail-under=90`

Зависимости CI: postgres:18-alpine, redis:8-alpine, python 3.13.

---

## 10. Сводка: статус компонентов

| Компонент | Статус | Примечание |
|---|---|---|
| YouTube плеер | ✅ | Через `video_url`, валидация ID |
| Внешние плееры (embed) | ✅ | Белый список (YouTube, Vimeo, Rutube) |
| Vibix плеер (data-type="kp") | ✅ | Без API-токена, browser-side резолвинг |
| Vibix плеер (data-type="movie") | ❌ | player_id="326" — это kp_id, а не video ID |
| Синхронизация player_id | ❌ | **Корневая причина:** неверный домен `api.vibix.org` (надо `vibix.org`) |
| Синхронизация озвучек | ❌ | Зависит от API-токена (тот же неверный домен) |
| Переключение серий | ✅ | `updateExternalPlayer()` в title-detail.js |
| WatchParty | ✅ | watch-party.js + sync.videoframe2.com |
| data-design (1–6) | ✅ | `VIDEO_SERVICE_DESIGN` из settings |
| Рекламная сеть (ADS_NETWORK) | ✅ | `vibix_union` в base.html + ad_slot.html |
| Микроразметка Vibix | ❌ | Не реализована (нет vibix_schema_microdata) |
| Тесты | ✅ | 477 тестов, 95% покрытие |
| ruff + mypy | ✅ | 0 ошибок |

---

## 11. Рекомендации

### Этап 1: Исправить player_id (без API)
Удалить неверный `player_id="326"` для Шоошенка. Когда `player_id` пуст,
`_get_external_player()` использует `kp_id` с `data-type="kp"` — SDK Vibix
разрешает его в браузере без API-токена.

### Этап 2: Наладить синхронизацию API
1. **Исправить базовый URL:** в `base.py` default и `.env.example`
   `VIBIX_API_BASE_URL` = `https://api.vibix.org/api/v1` → нужно
   `https://vibix.org/api/v1` (согласно официальной документации Vibix).
2. Если Bearer всё ещё не работает — попробовать session-based auth
   (scripts/vibix_session_test.py) с `VIBIX_USERNAME`/`VIBIX_PASSWORD`.
3. Запустить `sync_video_service --full` для получения реальных player_id.

### Этап 3: Наблюдаемость
В `_embed_player()` добавить логирование, когда `embed_code` пуст —
чтобы отследить записи, попадающие на fallback с внутренним `item["id"]`.

---

## 12. Ключевые выводы

1. **Архитектура чистая и well-engineered.** 477 тестов, 95% покрытие,
   ruff+mypy чисто, CI зелёный. Код снабжён подробными docstring-ами.

2. **Vibix плеер на клиенте работает без API-токена.** SDK `rendex-sdk.min.js`
   решает `data-type="kp" data-id="326"` в браузере. Токен нужен ТОЛЬКО
   для серверной синхронизации (sync_video_service, sync_voiceovers).

3. **Главная проблема — player_id="326"** ошибочно установлен как внутренний ID
   плеера, хотя это kp_id Шоошенка. Плеер пытается загрузить видео с ID 326
   в типе "movie", но такого видео нет (326 — Kinopoisk ID).

4. **Настоящие player_id** (из экспериментальных HTML-файлов):
   - Остров возрождения: 326776
   - Интерстеллар: 4433
   - Начало: 4427
   - Игра в кальмара (сериал): 222

5. **Сериалы** используют отдельный API-хост без `/publisher` префикса —
   код правильно это обрабатывает.

6. **Синхронизация** построена правильно: «только пустые поля», фильтр по году,
   инкрементальность, ретраи с экспоненциальной задержкой.

7. **Корневая причина неработающего API-токена — неверный домен.** Официальная
   документация Vibix (vibix.org) указывает базовый URL `https://vibix.org/api/v1`,
   а `base.py` default и `.env.example` используют `https://api.vibix.org/api/v1`
   (субдомен `api.`). Исправление: `VIBIX_API_BASE_URL = "https://vibix.org/api/v1"`.

8. **Рекламная сеть реализована** (`ADS_NETWORK_ENABLED`), микроразметка Vibix —
   не реализована. Учётные данные session auth: `VIBIX_USERNAME`/`VIBIX_PASSWORD`
   присутствуют в `.env`.