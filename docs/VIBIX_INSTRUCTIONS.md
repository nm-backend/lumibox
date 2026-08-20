# Инструкция по работе с Vibix

Переведённая из Google Docs — **официальная документация Vibix** для DLE-плагина.

---

## 1. Установка и обновление плагина DLE

### Загрузка плагина
Перейти по ссылке `https://plugins.vibix.org/v1/vibix.zip` и сохранить архив.

### Установка
1. Открыть панель DLE → **Утилиты → Управление плагинами → Загрузить плагин**.
2. Выбрать файл → **Загрузить плагин**.
3. В меню **Сторонние модули → Vibix - видеобалансер** ввести **API token**
   из личного кабинета.
4. Проставить базовое сопоставление полей (обязательно: "ссылка на плеер Vibix"
   и "Кинопоиск ID").

### Обновление
При уведомлении о версии: **Управление плагинами → Vibix → "Проверить наличие новых версий"**.

### Функционал плагина

| Раздел | Назначение |
|---|---|
| Каталог | Список фильмов с фильтрами. Наличие на сайте — зелёный флажок; отсутствующие можно запросить |
| Настройки | API token, автор публикаций, шаблоны SEO |
| Сопоставление полей | Связь полей базы Vibix с DLE. Обязательны: «ссылка на плеер Vibix» и «Кинопоиск ID» |
| Сопоставление категорий | Соответствие категорий сайта и базы Vibix |
| Статистика | Показ статистики в выбранном диапазоне дат |
| Профиль | Данные аккаунта |
| Запросы и заявки | Активные заявки на добавление фильмов |
| Фоновые задания | Подготовленные задания; запуск вручную или автозапуск |

---

## 2. Выбор фильмов / сериалов

- **Способ 1 (ручной):** отметить нужные флажками → селект **"Только с выбранными"**.
- **Способ 2 (фильтры):** задать комбинацию фильтров (рекомендуется
  **"Только в наличии"**) → селект **"Со всей выборкой по фильтру"**.

---

## 3-5. Добавление и обновление контента

Выбрав нужные фильмы (вручную или фильтром) и установив селект выборки:

| Действие | Кнопка |
|---|---|
| Добавить новые (не трогать существующие) | **"Добавить если нет"** |
| Добавить новые + обновить существующие | **"Добавить и обновить если есть"** |

### 5. Установка ссылки плеера

**В выбранные новости:**
Выбрать фильмы → селект выборки → кнопка **"Проставить ссылку на плеер Vibix"**
→ ссылка прописывается в доп. поле DLE.

**Сразу во все новости:**
Выбрать фильтр **"Только в наличии"** → селект **"Со всей выборкой по фильтру"**
→ опция **"Проставить ссылку на плеер Vibix"** → запустить задание.

---

## 6. Запуск заданий Cron

| Способ | Как |
|---|---|
| Вручную | **Фоновые задания → "Запустить задания вручную"** |
| Авто | Планировщик Cron: `GET /cron_vibix.php` (ежеминутно) |

---

## 7. Микроразметка (JSON-LD + Open Graph)

Создать доп. поля DLE:
- `vibix_schema_microdata` — JSON-LD
- `vibix_og_microdata` — Open Graph

В `main.tpl` после `<head>`:
```smarty
[xfgiven_vibix_schema_microdata]
<script type="application/ld+json">[xfvalue_vibix_schema_microdata]</script>
[/xfgiven_vibix_schema_microdata]

[xfgiven_vibix_og_microdata]
[xfvalue_vibix_og_microdata]
[/xfgiven_vibix_og_microdata]
```

---

## 8. Рекламный код

Перед `</head>`:
```html
<script type="text/javascript"
  src="https://v-js-menu.run/public/lib.en.min.js"></script>
```

Внутри `<body>`:
```html
<ins id="vibix_union" data-publisher_id="678503345"
  data-add_types="brand,sticker,pcsticker,banners,flyroll"></ins>
```

**Поддерживаемые форматы `data-add_types`:**
`sticker`, `pcsticker`, `banners`, `brand`, `flyroll`.

---

## 9. Подключение плеера

В `<head>`:
```html
<script src="https://graphicslab.io/sdk/v2/rendex-sdk.min.js"></script>
```

**Пример использования:**
```html
<!-- data-type="movie" data-id="1" — реальный Video ID -->
<ins data-publisher-id="678503345" data-type="movie" data-id="1"></ins>

<!-- data-type="kp" data-id="326" — Kinopoisk ID (Шоошенк), browser-side резолвинг -->
<ins data-publisher-id="678503345" data-type="kp" data-id="326"></ins>
```

**Ключевые типы `data-type`:**
| Тип | data-id содержит | Примечание |
|---|---|---|
| `movie` | Внутренний Video ID Vibix | Требует знания ID |
| `kp` | Kinopoisk ID | Разрешается браузером **без API-токена** |
| `imdb` | IMDb ID | Разрешается браузером **без API-токена** |

---

## 9.2 Параметры плеера

### data-design (1–6)
| Значение | Описание |
|---|---|
| 1 | По умолчанию |
| 2 | Монохром |
| 3 | Синий Неон |
| 4 | Ютуб |
| 5 | Ночной Минимализм |
| 6 | Карусель эпизодов |

---

## 10. API документация

### Базовые URL
- **Swagger / OpenAPI:** `https://vibix.org/api/external/documentation`
- **API base:** `https://vibix.org/api/v1`
- **Auth header:** `Authorization: Bearer {API_KEY}`
  - Токен из `.env.example`: `29756|4yaXH5dIT0A2EtB27D55qUlYmfc28MzM3875wtj4800a4f63`

### GET-методы

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/v1/publisher/videos/kp/{kpId}` | Видео по Kinopoisk ID |
| GET | `/api/v1/publisher/videos/imdb/{imdbId}` | Видео по IMDb ID |
| GET | `/api/v1/publisher/videos/links` | Список загруженных видео |
| GET | `/api/v1/publisher/videos/get_kpids` | Список kp_id |
| GET | `/api/v1/publisher/videos/categories` | Категории |
| GET | `/api/v1/publisher/videos/genres` | Жанры |
| GET | `/api/v1/publisher/videos/countries` | Страны |
| GET | `/api/v1/publisher/videos/tags` | Теги |
| GET | `/api/v1/publisher/videos/voiceovers` | Озвучки |
| GET | `/api/v1/serials/kp/{kpId}` | Сезоны и серии по Kinopoisk ID |
| GET | `/api/v1/serials/imdb/{imdbId}` | Сезоны и серии по IMDb ID |

**Важно:** серийные эндпоинты (`/serials/...`) работают **без** `/publisher`
префикса — это соответствует `VIDEO_SERVICE_SERIALS_API_BASE` в `video_service_api.py`.

---

## 11. Совместный просмотр (WatchParty)

```html
<ins id="vibix-frame-id"
  data-publisher-id="678503345"
  data-type="movie"
  data-id="1"
  data-sync="true"></ins>

<script src="https://graphicslab.io/sdk/v2/rendex-sdk.min.js"></script>
<script src="https://sync.videoframe2.com/sync-lib.js"></script>
<script>
new WatchParty({ iframe: '#vibix-frame-id' });
</script>
```

---

## Соответствие с архитектурой LumiBox

| Инструкция | Реализация в LumiBox |
|---|---|
| `https://vibix.org/api/v1` | Правильный URL — только в `render.yaml`/`render.paid.yaml`; **default `base.py` = `api.vibix.org` (баг!)** |
| `https://api.vibix.org/api/v1` | `.env.example` и `.env` — **НЕВЕРНО**, корень ошибки 8.2! |
| `/publisher/videos/kp/{id}` | `fetch_video_by_kp()` в `video_service_api.py` |
| `/serials/kp/{id}` (без /publisher) | `fetch_serial_by_kp()` + `VIDEO_SERVICE_SERIALS_API_BASE` |
| `Authorization: Bearer {API_KEY}` | `get_vibix_api_token()` в `video_service_api.py` |
| `rendex-sdk.min.js` | Подключается в `title_detail.html` через `static/js/title-detail.js` |
| `data-type="kp" data-id="326"` | Fallback в `_get_external_player()` когда `player_id` пуст |
| `data-design` (1–6) | `VIDEO_SERVICE_DESIGN` в settings |
| `vibix_union` реклама | **реализовано** (`ADS_NETWORK_*` + `base.html` + `ad_slot.html` + CSP) |
| Микроразметка | **не реализована** в LumiBox |