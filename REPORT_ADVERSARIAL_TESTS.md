# Адверсариальное тестирование LumiBox — отчёт

## Команда воспроизведения

```
$env:DJANGO_SETTINGS_MODULE="config.settings.development"
python -m pytest apps/catalog/tests/test_adversarial_api.py apps/catalog/tests/test_adversarial_auth.py apps/catalog/tests/test_adversarial_xss.py apps/catalog/tests/test_adversarial_validation.py apps/catalog/tests/test_adversarial_media.py -q --no-header
```

Итог: **8 failed, 94 passed** (102 теста, 5 файлов).

Легенда: `FAILED` — подтверждённая поломка (атака воспроизведена); `passed` — атака заблокирована защитой, тест фиксирует работу защиты.

---

## Подтверждённые баги (8)

### 1. Краш API рейтинга на не-dict JSON-теле → 500
Файл: `apps/catalog/tests/test_adversarial_api.py`, класс `RateTitleViewCrashTests`:
- `test_rate_title_500_on_json_array_body`
- `test_rate_title_500_on_json_string_body`
- `test_rate_title_500_on_json_number_body`

Атака: `POST /api/v1/titles/<slug>/rate/` с телом `[1,2,3]` / `"x"` / `5` и `Content-Type: application/json`.

Поведение: `RateTitleView` (apps/api/v1/views.py) вызывает `request.data.get("rating")`; для списка/строки/числа это `AttributeError: 'list' object has no attribute 'get'` — в боевом окружении 500, в тесте исключение пере-поднимается тестовым клиентом.

Ожидание: 400 Bad Request.

### 2. Логическая оценка как число → сохраняется рейтинг 1
Файл: `apps/catalog/tests/test_adversarial_api.py`, `RateTitleViewCrashTests::test_rate_title_accepts_boolean_rating`

Атака: `{"rating": true}` (JSON-логическое). В Python `bool` — подкласс `int`, `True == 1`, поэтому проверки `isinstance(rating, int)` и `1 <= rating <= 10` проходят, создаётся отзыв с рейтингом 1.

Поведение: 200, отзыв создан. Ожидание: 400.

### 3. Ответ на скрытый комментарий принимается
Файл: `apps/catalog/tests/test_adversarial_api.py`, `CommentApiModerationTests::test_comment_reply_to_hidden_parent_allowed`

Атака: создаётся комментарий на публичном тайтле, родитель скрывается (status=HIDDEN), затем `POST /api/v1/titles/<slug>/comments/` с `{"text": ..., "parent": <pk>}`.

Поведение: 201, комментарий-ответ создан — `save_comment` (apps/reviews/services.py) проверяет только принадлежность parent к тайтлу, не статус. Ожидание: 400 — отвечать на скрытое нельзя.

### 6→4. Родитель с чужого тайтла молча сбрасывается
Файл: `apps/catalog/tests/test_adversarial_api.py`, `CommentApiModerationTests::test_comment_cross_title_parent_silently_dropped`

Атака: `parent` указывает на комментарий другого тайтла. `save_comment` не находит совпадения и создаёт корневой комментарий, **молча теряя parent**.

Поведение: 201 с `parent=null`. Ожидание: 400 — ошибка валидации, а не тихая потеря связи.

### 5. Позиция прогресса без верхней границы
Файл: `apps/catalog/tests/test_adversarial_api.py`, `WatchProgressBoundaryTests::test_watch_progress_accepts_absurd_position`

Атака: `POST /api/v1/titles/<slug>/watch/` с `{"episode": <pk>, "position": 2**40}`.

Поведение: 200, значение сохранено (на sqlite помещается, на PostgreSQL — DataError/переполнение). Ожидание: 400 — `EpisodeWatchRequestSerializer` не задаёт `max_value`.

### 6. Валидация YouTube ID не совпадает между модулями
Файл: `apps/catalog/tests/test_adversarial_api.py`, `EmbedValidationTests::test_short_youtube_id_rejected`

Атака: `youtube.py` требует ровно 11 символов ID; `embeds._youtube` (apps/catalog/embeds.py) строит embed-URL для любого значения `v=` без проверки длины.

Поведение: для `v=abc` возвращается embed-URL. Ожидание: None — невалидный ID отклоняется.

---

## Заблокированные атаки (94 теста — защита работает)

| Направление | Файл | Кол-во | Что проверено |
|---|---|---|---|
| API-границы | test_adversarial_api.py | 29 | rating 0/11/дробь/строка, текст 2001, parent 999999, page garbage, поиск-лимиты, черновики скрыты, сортировка-мусор, unknown-host embed, protocol-relative embed, дробная позиция (400) |
| Авторизация | test_adversarial_auth.py | 21 | guest→302 на все мутации, IDOR (web 404 / API 403), logout GET→405, rate limit регистрации 429, дубль email (в т.ч. с регистром), черновики→404 везде |
| XSS | test_adversarial_xss.py | 14 | stored XSS (имя тайтла, отзыв, комментарий, username, bio, эпизод, жанр), JSON-LD breakout `</script>`, og-meta, reflected XSS в поиске, attribute breakout |
| Валидация | test_adversarial_validation.py | 15 | rating 0/11/«мусор» (web 400), текст 2001 (web+API), page/sort/year garbage, дедупликация отзывов (обновление, не дубль) |
| Медиа | test_adversarial_media.py | 15 | traversal (.., %2e%2e, обратный слэш, абсолютный путь) → 404, private_media → 404, Range 206/416/200, огромный Range без 500 |

## Примечания

- `test_watch_progress_truncates_float_position` — сериализатор **отклоняет** дробную позицию (400): тихого усечения нет, защита работает.
- DRF-пагинация: `?page=999999999` и `?page=abc` → 404, `?release_year=abc` → 400 — мусорные параметры не валят каталог.
- Формы отзывов/комментариев возвращают 400 на невалидные данные (а не перерисовку с 200).
- Emails нормализуются в lowercase на уровне менеджера + формы (регистр-дубль невозможен).
- Rate limit регистрации: 10 попыток проходят, 11-я — 429.
- В тестах клиента `raise_request_exception=False` не подавляет повторный подъём исключения (Django test client) — краш-тесты фиксируют падение через сам факт исключения; в проде это 500.