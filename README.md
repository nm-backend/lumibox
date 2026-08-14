# LumiBox

Кинопортал на Django: каталог с разделами и фильтрами, плеер с выбором
озвучки и продолжением просмотра, поиск, подборки и франшизы, личная
библиотека, отзывы с оценками, обсуждения, рекомендации, REST API
и админ-панель.

Собственный дизайн, светлая и тёмная темы, адаптивная вёрстка. Без
CSS-фреймворков и SPA — только Django Templates, чистый CSS и ванильный
JavaScript без сборки.

Проект поднимается одной командой: `docker compose up --build -d`.

---

## Возможности

**Каталог**
- Фильмы, сериалы, мультфильмы, аниме и ТВ-шоу в одной модели `Title`
  с полем «тип» — один каталог, один поиск, одно избранное вместо
  параллельных веток
- Разделы-витрины: новинки, популярное, топ по рейтингу, премьеры,
  страница года. Каждый — тот же каталог с суженной выборкой, поэтому
  фильтры и сортировка работают и в них
- Фильтры: тип, жанр, страна, точный год, диапазон лет, минимальный
  рейтинг, качество, возраст, озвучка
- Страницы жанров, стран, персон, студий, премий, франшиз и подборок
- Франшизы: блок «Все части» на странице записи, в порядке выхода
- Пагинация с сокращённым диапазоном (`1 … 4 5 6 … 12`)
- Черновики: запись не видна нигде, пока редактор её не опубликовал

**Поиск**
- Один сервис на весь проект: страница `/search/`, подсказки в шапке и
  фильтр каталога находят одно и то же
- Ищет по названию, оригиналу, описаниям, жанру, стране, студии и людям
- Подсказки с клавиатурной навигацией

**Просмотр**
- YouTube — основной источник видео MVP: у фильма два отдельных поля —
  `trailer_url` (трейлер) и `video_url` (полная версия), у серии сериала —
  `video_url`. Ролики не смешиваются, вкладки «Смотреть фильм» и «Трейлер»
  открывают свои
- Из ссылки извлекается только ID ролика (`apps/catalog/youtube`):
  принимаются `watch`, `youtu.be` и `embed`, чужой домен или произвольный
  iframe-адрес в плеер не попадут
- Серии сгруппированы по сезонам; выбор серии открывает её ролик
- Свои файлы и внешние плееры остаются запасными вкладками:
  `PlaybackSource` (файл или эмбед с доверенного хоста, с выбором озвучки)
  и внешний плеер по ID Кинопоиска/IMDb или внутреннему ID видео

**Пользователи**
- Своя модель `User`, вход по электронной почте
- Регистрация со входом сразу после неё
- Профиль с аватаром, био и счётчиками

**Личная библиотека**
- Избранное и «смотреть позже» с переключателем без перезагрузки страницы
- История просмотров с очисткой

**Отзывы, оценки и обсуждения**
- Оценка от 1 до 10, один отзыв на запись от пользователя
- Комментарии с ответами (один уровень вложенности) и модерацией
- Модерация: скрытый отзыв не влияет на рейтинг, скрытый комментарий
  уходит вместе со своими ответами
- Рейтинг денормализован в поля модели — списки не делают `AVG` с `JOIN`

**Рекомендации**
- Похожее по числу совпавших жанров
- Персональные подборки по избранному пользователя

**API**
- REST API на DRF, версионированный (`/api/v1/`)
- Swagger UI и ReDoc, схема собирается из кода
- Ограничение частоты: 60 запросов в минуту гостю, 300 авторизованному

**SEO**
- Метатеги с запасным вариантом из названия и описания
- `sitemap.xml` и `robots.txt`

**Админ-панель**
- Полное управление каталогом без правки кода
- Съёмочная группа и содержимое подборок редактируются инлайнами
- Массовые действия: публикация, снятие с публикации, модерация отзывов

**Инфраструктура**
- Docker: раздельные окружения для разработки и боя
- Redis как кэш и брокер, Celery для фоновых задач
- **Redis необязателен**: без него кэш работает в памяти процесса,
  а задачи выполняются в запросе — проект поднимется и без Redis

---

## Стек

| Слой | Технологии |
|---|---|
| Язык | Python 3.13 (в контейнере), 3.13+ локально |
| Backend | Django 5.2 LTS, Django REST Framework 3.17 |
| База | PostgreSQL 18, psycopg 3 |
| Кэш и очередь | Redis 8, Celery 5.6 |
| Документация API | drf-spectacular (Swagger UI, ReDoc, OpenAPI 3) |
| Frontend | Django Templates, CSS3, ванильный JavaScript |
| Боевой сервер | Gunicorn, WhiteNoise |
| Инфраструктура | Docker, Docker Compose |
| Качество | ruff, coverage, встроенный тест-раннер Django |

Django 5.2 выбран намеренно: это LTS с поддержкой безопасности до апреля 2028,
что для проекта, который живёт годами, важнее свежести.

---

## Требования

Для запуска через Docker достаточно двух программ. Ни Python, ни PostgreSQL,
ни Redis ставить на машину **не нужно** — всё поднимается в контейнерах.

| Программа | Версия | Зачем |
|---|---|---|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | 20.10+ | база, кэш, сайт, воркер |
| [Git](https://git-scm.com/downloads) | любая | скачать проект |

Docker Compose входит в Docker Desktop, отдельно ставить не нужно.

Проверьте установку — все три команды должны отработать без ошибок:

```bash
docker --version
docker compose version
docker info
```

Если `docker info` пишет `Cannot connect to the Docker daemon` — Docker Desktop
не запущен. Откройте его и дождитесь, пока иконка кита перестанет мигать.

**Без Docker** понадобится Python 3.13+, PostgreSQL 18 и, по желанию, Redis —
см. раздел [Запуск без Docker](#запуск-без-docker).

---

## Быстрый запуск

### 1. Клонирование

```bash
git clone <адрес-репозитория> LumiBox
cd LumiBox
```

### 2. Создание .env

В проекте есть образец `.env.example`. Скопируйте его:

```bash
# Linux, macOS, Git Bash
cp .env.example .env
```

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

Откройте `.env` и заполните **два обязательных значения**.

**`DJANGO_SECRET_KEY`** — секретный ключ Django. Сгенерируйте случайный:

```bash
docker run --rm python:3.13-slim python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Вставьте вывод:

```
DJANGO_SECRET_KEY=вставьте-сюда-сгенерированный-ключ
```

**`POSTGRES_PASSWORD`** — пароль базы. Придумайте любой, он используется
только внутри контейнеров:

```
POSTGRES_PASSWORD=lumibox-local-pass
```

**Тот же пароль должен стоять в `DATABASE_URL`** — это два разных места
в файле, и они обязаны совпадать:

```
DATABASE_URL=postgres://lumibox:lumibox-local-pass@localhost:5433/lumibox
```

Остальные строки менять не нужно.

> `.env` не попадает в git — он в `.gitignore`. Свои пароли вы никуда не отправите.

### 3. Запуск

```bash
docker compose up --build -d
```

Первый запуск занимает 2–5 минут: Docker скачивает образы и собирает проект.
Флаг `-d` запускает в фоне и освобождает терминал.

**Миграции применяются автоматически при старте** — отдельная команда не нужна.

### 4. Проверка контейнеров

```bash
docker compose ps
```

Ожидаемый вывод — четыре сервиса, у `db` и `redis` статус `healthy`:

```
NAME                 SERVICE   STATUS
lumibox-db-1        db        Up (healthy)
lumibox-redis-1     redis     Up (healthy)
lumibox-web-1       web       Up
lumibox-worker-1    worker    Up
```

Если `web` перезапускается — смотрите причину: `docker compose logs web`.

### 5. Миграции

Применяются сами при старте. Команда нужна, только если что-то пошло не так:

```bash
docker compose exec web python manage.py migrate
```

Проверить, что неприменённых миграций нет:

```bash
docker compose exec web python manage.py migrate --check
```

### 6. Наполнение каталога

```bash
docker compose exec web python manage.py seed_catalog
```

Создаст 14 жанров, 11 стран и 16 фильмов и сериалов (14 опубликованных
и 2 черновика — на них видно, что каталог показывает только опубликованное).

Команда идемпотентна: повторный запуск обновит записи, а не создаст дубликаты.

Очистить каталог перед наполнением:

```bash
docker compose exec web python manage.py seed_catalog --clear
```

### 7. Создание администратора

```bash
docker compose exec web python manage.py createsuperuser
```

Команда спросит три значения:

- **Электронная почта** — это логин. Вход по почте, а не по имени пользователя
- **Имя пользователя** — публичное имя рядом с отзывами
- **Пароль** — минимум 8 символов, не только цифры, не из словаря частых

### 8. Проверка

| Адрес | Что это |
|---|---|
| http://localhost:8001/ | Сайт |
| http://localhost:8001/catalog/ | Каталог с фильтрами |
| http://localhost:8001/admin/ | Админ-панель |
| http://localhost:8001/api/v1/titles/ | REST API |
| http://localhost:8001/api/docs/ | **Swagger UI** — документация с выполнением запросов |
| http://localhost:8001/api/redoc/ | **ReDoc** — документация для чтения |
| http://localhost:8001/api/schema/ | Схема OpenAPI в YAML |
| http://localhost:8001/sitemap.xml | Карта сайта |

---

## Видео: YouTube-плеер MVP

Для базового просмотра зависимостей нет: каталог наполняется ссылками
на YouTube и работает сам по себе.

### Чем показывается видео

У каждой записи два независимых поля:

- `trailer_url` — трейлер (отдельный ролик);
- `video_url` — полная версия фильма;
- у серии сериала — своё `video_url` на каждую серию.

Оба поля принимают только YouTube-ссылки (`watch`, `youtu.be`, `embed`).
Из ссылки парсер `apps/catalog/youtube` извлекает 11-символьный ID
ролика, а embed-адрес собирает сам бэкенд — редактор не может вставить
в iframe произвольный адрес или чужой домен. Пустое поле означает
«видео нет»: плеер просто не появится.

На странице записи вкладки: «Смотреть фильм» (или «Смотреть серии»)
и «Трейлер» — это разные ролики, они не подменяют друг друга. Если
вкладок несколько (свой файл, внешний плеер), все они остаются
доступны.

### Запасные источники

- `PlaybackSource` — свои видеофайлы (mp4/webm/ogg) или эмбед
  с доверенного хоста, у серии — на каждой серии, с выбором озвучки.
  Встраивается в iframe только хост из белого списка.
- Внешний плеер по ID Кинопоиска/IMDb или внутреннему ID видео —
  опциональная интеграция с внешним видеосервисом (см. ниже).

## Опциональная интеграция с внешним видеосервисом

Для базового просмотра она не нужна: YouTube-плеер MVP работает без
каких-либо ключей. Интеграция добавляет вкладку «Внешний плеер»
и автоматическую простановку идентификаторов.

### Плеер

Вкладка «Внешний плеер» появляется, когда у записи заполнен `player_id`
(внутренний ID видео — официальный формат тега) либо `kp_id`/`imdb_id`
(поля «ID на Кинопоиске» / «ID на IMDb» в админке). Для kp/imdb-варианта
плеер получает `data-trailer` — по умолчанию `"true"`: покажет трейлер,
если полного видео нет в каталоге сервиса (режим задаёт
`VIDEO_SERVICE_TRAILER`, см. таблицу). SDK и тег `<ins>` подключаются
только на таких страницах. Пустой `VIDEO_SERVICE_PUBLISHER_ID`
в настройках отключает интеграцию целиком.

### Синхронизация ID

Команда тянет список видео из API видеосервиса и проставляет
`kp_id`/`imdb_id`/`player_id` записям каталога по совпадению названия
и года. Заполняются только пустые поля — вручную введённые ID
не затираются. Параллельно запись обогащается данными карточки API:
описание, рейтинги Кинопоиска/IMDb, длительность и оригинальное
название (тоже только пустые поля), а жанры и страны заводятся
в справочники, если их ещё нет. Первый прогон фильтрует каталог
по годам записей и занимает минуты, дальше идёт по отметке
`updated_from` и подхватывает только новые/изменённые видео.

```bash
docker compose exec web python manage.py sync_video_service            # инкрементально
docker compose exec web python manage.py sync_video_service --full     # весь каталог
docker compose exec web python manage.py sync_video_service --dry-run  # только отчёт
```

По расписанию задачу запускает Celery beat раз в сутки
(`sync_video_service`); без `VIDEO_SERVICE_API_KEY` она пропускается.

Серии сериалов (сезоны и эпизоды) импортируются отдельной командой
`sync_episodes` — она тянет `GET /serials/kp|imdb/{id}` для записей
без единой серии и создаёт недостающие, повторный запуск ничего
не дублирует:

```bash
docker compose exec web python manage.py sync_episodes            # импортировать серии
docker compose exec web python manage.py sync_episodes --dry-run  # только отчёт
```

Сериалы живут на отдельном адресе API (`/api/v1/serials/...` без
префикса `/publisher`) — клиент учитывает это автоматически.

### Настройки

| Переменная | Назначение |
|---|---|
| `VIDEO_SERVICE_API_KEY` | Ключ API видеосервиса (`Authorization: Bearer`). Без него синк невозможен |
| `VIDEO_SERVICE_PUBLISHER_ID` | ID издателя для плеера (тег `data-publisher-id`) |
| `VIDEO_SERVICE_DESIGN`, `VIDEO_SERVICE_COLOR1..5` | Оформление внешнего плеера (дизайн 1–6 и цвета для кастомизируемых) |
| `VIDEO_SERVICE_AUTOPLAY` | Автовоспроизведение внешнего плеера (`data-autoplay`), выключено |
| `VIDEO_SERVICE_WATCH_PARTY` | Совместный просмотр (`data-sync` + sync-lib + WatchParty, комната — адрес записи), выключено |
| `VIDEO_SERVICE_TRAILER` | Трейлер для kp/imdb-эмбедов (`data-trailer`): `true` — если полного видео нет, `only` — всегда трейлер, пусто — без параметра |
| `ADS_NETWORK_ENABLED` | Рекламная сеть, по умолчанию выключена |
| `ADS_NETWORK_PUBLISHER_ID`, `ADS_NETWORK_ADD_TYPES` | Параметры рекламной сети |

Ключ хранится только в `.env` или окружении сервера — в код и репозиторий
он не попадает.

---

## Наполнение каталога через админку

Всё наполняется в `/admin/` без правки кода.

**Фильм за три минуты:**

1. «Фильмы и сериалы» → «Добавить фильм или сериал».
2. В секции **Основная информация** — название, год, тип, статус
   «Опубликовано».
3. В секции **Видео** — вставьте ссылки: `video_url` (полная версия
   на YouTube) и, по желанию, `trailer_url` (трейлер). Оба принимают
   `watch`, `youtu.be` или `embed`; чужой домен форма не пропустит.
4. В секции **Категории** — жанры и страны. Постер и фон — в секции
   **Изображения**.
5. «Сохранить» — запись сразу видна на сайте: вкладка «Смотреть фильм»
   открывает `video_url`, «Трейлер» — трейлер.

**Сериал с сериями:**

1. Создайте запись с типом «Сериал» и заполните секцию **Видео**
   (трейлер опционален).
2. Ниже, в инлайне **Серии**, добавьте сезон, номер и название серии
   и её `video_url`. Поле «Сезон» группирует серии по сезонам
   автоматически; пары «сезон + серия» уникальны в пределах сериала.
3. После сохранения на странице сериала появится вкладка
   «Смотреть серии»: выбор серии открывает её ролик.

Только-YouTube ссылки в админке помечены подсказкой прямо у поля;
ID Кинопоиска/IMDb и `player_id` (внешний плеер) заполняются
синхронизацией или вручную в секции **Идентификаторы**.

---

## Запуск тестов

```bash
docker compose exec web python manage.py test apps
```

**648 тестов** (3 отмечены skip), около минуты. Ожидаемый результат — `OK`.

Тесты создают собственную временную базу и удаляют её после прогона —
ваши данные не пострадают.

Тесты одного приложения или одного файла:

```bash
docker compose exec web python manage.py test apps.catalog
docker compose exec web python manage.py test apps.api
docker compose exec web python manage.py test apps.catalog.tests.test_publication_flow
```

Подробный вывод с именами тестов:

```bash
docker compose exec web python manage.py test apps -v 2
```

### Покрытие

```bash
docker compose exec web coverage run --source=apps \
  --omit="*/migrations/*,*/tests.py,*/tests/*,*/test_*.py" \
  manage.py test apps

docker compose exec web coverage report
```

Текущее покрытие — **95%**. Нижняя планка зашита в CI (`coverage report --fail-under=90`). Показать только непокрытые файлы:

```bash
docker compose exec web coverage report --skip-covered --sort=cover
```

### Что покрыто

- Модели, менеджеры, QuerySet'ы, валидаторы
- Сервисный слой: рекомендации, похожее, рейтинг, кэш
- Права доступа: чужой отзыв, чужое избранное, утечка черновиков
- Гонки: двойной клик по избранному, двойная отправка отзыва
- Полный цикл публикации от админки до всех витрин сайта
- API: сериализаторы, права на уровне объекта, ограничение частоты
- Защита от N+1: число запросов не растёт с числом карточек

---

## Проверка качества

Все четыре команды должны проходить без замечаний.

```bash
# Линтер: неиспользуемые импорты, мёртвые переменные, порядок импортов, стиль
docker compose exec web ruff check apps config

# Проверка конфигурации Django
docker compose exec web python manage.py check

# Проверка боевых настроек: HTTPS, cookie, заголовки безопасности
docker compose exec web sh -c 'DJANGO_SETTINGS_MODULE=config.settings.production \
  DJANGO_ALLOWED_HOSTS=example.com python manage.py check --deploy'

# Миграции не отстают от моделей
docker compose exec web python manage.py makemigrations --check --dry-run
```

Проверка схемы API — должна собираться без предупреждений:

```bash
docker compose exec web python manage.py spectacular --file /tmp/schema.yml
```

Автоисправление того, что ruff умеет чинить сам:

```bash
docker compose exec web ruff check apps config --fix
```

---

## Docker: полезные команды

### Управление

```bash
# Запустить (в фоне)
docker compose up -d

# Запустить с пересборкой — нужно после изменения requirements или Dockerfile
docker compose up --build -d

# Статус сервисов
docker compose ps

# Остановить, сохранив данные
docker compose stop

# Запустить остановленные
docker compose start

# Перезапустить один сервис
docker compose restart web
```

### Логи

```bash
# Все сервисы, в реальном времени
docker compose logs -f

# Один сервис
docker compose logs -f web
docker compose logs -f worker

# Последние 50 строк
docker compose logs --tail 50 web

# Только ошибки
docker compose logs web | grep -i error
```

### Вход в контейнеры

```bash
# Оболочка внутри контейнера сайта
docker compose exec web sh

# Django shell
docker compose exec web python manage.py shell

# Консоль PostgreSQL
docker compose exec db psql -U lumibox -d lumibox

# Консоль Redis
docker compose exec redis redis-cli
```

### Диагностика

```bash
# Celery видит брокер и знает свои задачи?
docker compose exec worker celery -A config inspect ping
docker compose exec worker celery -A config inspect registered

# Redis отвечает?
docker compose exec redis redis-cli ping        # ожидаем PONG

# Конфигурация compose корректна?
docker compose config --quiet
docker compose -f docker-compose.prod.yml config --quiet
```

### Удаление

```bash
# Удалить контейнеры и сеть. Данные в базе СОХРАНЯТСЯ
docker compose down

# Удалить всё вместе с томами. Данные пропадут безвозвратно
docker compose down -v

# Дополнительно удалить собранные образы
docker compose down -v --rmi local
```

После `down -v` следующий запуск будет как первый: пустая база, нужно снова
выполнить `seed_catalog` и `createsuperuser`.

### Пересборка с нуля

Если образ ведёт себя странно, соберите его, игнорируя кэш слоёв:

```bash
docker compose build --no-cache web
docker compose up -d
```

---

## Структура проекта

```
LumiBox/
├── apps/                        приложения проекта
│   ├── core/                    общее: абстрактные модели, валидаторы, миксины
│   │   ├── models.py            TimeStampedModel, SeoModel
│   │   ├── validators.py        проверка веса и разрешения картинок
│   │   ├── views.py             ElidedPaginationMixin
│   │   └── test_factories.py    фабрики объектов для тестов
│   ├── users/                   своя модель User, вход по почте, профиль
│   ├── catalog/                 ядро: фильмы, сериалы, справочники
│   │   ├── models/              пакет: title, reference, person, collection
│   │   ├── managers.py          TitleQuerySet: published, with_related, top_rated
│   │   ├── services.py          бизнес-логика: рекомендации, рейтинг, кэш
│   │   ├── signals.py           сброс кэша при публикации
│   │   ├── tasks.py             фоновый пересчёт рейтингов
│   │   ├── sitemaps.py          карта сайта
│   │   └── management/commands/ seed_catalog
│   ├── library/                 избранное и история просмотров
│   ├── reviews/                 отзывы с оценками и модерацией
│   └── api/                     REST API поверх тех же сервисов
│       └── v1/                  версия 1: serializers, views, urls
├── config/                      конфигурация проекта
│   ├── settings/                base / development / production
│   ├── celery.py                приложение Celery
│   ├── urls.py                  корневые маршруты
│   └── wsgi.py, asgi.py         точки входа для сервера
├── templates/                   шаблоны
│   ├── base.html                каркас: шапка, навигация, подвал
│   ├── catalog/                 главная, каталог, фильм, персона, подборки
│   ├── users/                   вход, регистрация, профиль
│   ├── library/                 избранное, история
│   └── includes/                переиспользуемые блоки и иконки
├── static/
│   ├── css/                     токены, каркас, компоненты, страницы
│   └── js/                      45 строк: кнопка избранного
├── media/                       файлы, загруженные через админку
├── requirements/                зависимости: base / development / production
├── Dockerfile                   4 стадии: base, builder, development, production
├── docker-compose.yml           локальная разработка
├── docker-compose.prod.yml      боевое окружение
└── ruff.toml                    настройки линтера
```

### Почему так

**Приложение зовётся `catalog`, а не `movies`.** Модель `Title` покрывает
и фильмы, и сериалы — имя `movies` врало бы с первого дня.

**Сервисный слой (`services.py`).** Здесь операции, нужные больше чем в одном
месте: их зовут и вьюхи сайта, и REST API. Держать такое во вьюхе значит
переписать второй раз для API — вместе с ошибками.

**Менеджеры (`managers.py`).** Фильтр «только опубликованное» нужен на главной,
в каталоге, в поиске и в рекомендациях. Забыть его в одном месте — показать
посетителям черновики. Один метод `published()` эту ошибку исключает.

**Два compose-файла.** В боевых настройках включён `SECURE_SSL_REDIRECT`,
и по `http://localhost` сайт уводил бы на https, которого локально нет.
Одним файлом это не решается.

**Порты 5433 и 6380.** База и Redis доступны с хоста на нестандартных портах:
5432 и 6379 обычно заняты локально установленными сервисами, и проект бы
с ними конфликтовал.

### Настройки

| Файл | Назначение |
|---|---|
| `config/settings/base.py` | общее для всех окружений |
| `config/settings/development.py` | локальная разработка, `DEBUG=True` |
| `config/settings/production.py` | бой: HTTPS, HSTS, защита cookie, WhiteNoise |

`manage.py` по умолчанию берёт настройки разработки, `wsgi.py` и `asgi.py` —
боевые. Умолчание безопасное: забыли задать переменную на сервере — получите
`DEBUG=False`, а не открытые всем трассировки.

---

## Типичные ошибки

### 1. `Cannot connect to the Docker daemon`

**Причина.** Docker Desktop не запущен.

**Решение.** Откройте Docker Desktop, дождитесь, пока иконка кита перестанет
мигать. Проверьте: `docker info` — должен вывести информацию о сервере.

### 2. `Задайте POSTGRES_PASSWORD в .env`

**Причина.** Файл `.env` не создан или переменная пустая. Compose останавливается
намеренно: молча поднять базу с пустым паролем хуже, чем упасть.

**Решение.** `cp .env.example .env`, затем заполните `POSTGRES_PASSWORD`
и `DJANGO_SECRET_KEY`.

### 3. `port is already allocated` / `bind: address already in use`

**Причина.** Порт занят другой программой. Снаружи проект использует
8001 (сайт), 5433 (база), 6380 (Redis) — все три намеренно смещены
относительно стандартных 8000/5432/6379, которые часто уже заняты
локальным PostgreSQL или соседним проектом.

**Решение.** Найдите, кто занял порт, и остановите его:

```bash
# Linux, macOS
lsof -i :8001
# Windows PowerShell
netstat -ano | findstr :8001
```

Либо поменяйте порт слева от двоеточия в `docker-compose.yml` —
менять нужно только левое число, внутри контейнера порт всегда 8000:

```yaml
ports:
  - "8002:8000"   # сайт станет доступен на localhost:8002
```

### 4. `dependency failed to start: container lumibox-db-1 exited`

**Причина.** База не поднялась. Чаще всего — остаток тома от другой версии
PostgreSQL: образ 18 хранит данные иначе, чем предыдущие.

**Решение.** Посмотрите причину и пересоздайте том:

```bash
docker compose logs db
docker compose down -v
docker compose up --build -d
```

### 5. `password authentication failed for user "lumibox"`

**Причина.** Пароль в `DATABASE_URL` не совпадает с `POSTGRES_PASSWORD`.
Это два разных места в `.env`, и их легко рассинхронизировать.

**Решение.** Приведите значения к одному. Если правили пароль после первого
запуска — база сохранила старый, нужен `docker compose down -v`.

### 6. `relation "catalog_title" does not exist`

**Причина.** Миграции не применились: контейнер стартовал раньше базы
или `migrate` упал.

**Решение.**

```bash
docker compose exec web python manage.py migrate
docker compose logs web | grep -i migrat
```

### 7. `Error 111 connecting to redis:6379. Connection refused`

**Причина.** Redis не поднялся или ещё стартует.

**Решение.**

```bash
docker compose ps redis          # должен быть healthy
docker compose logs redis
docker compose restart redis
```

Redis необязателен: уберите `REDIS_URL` из окружения — кэш переключится
на память процесса, а задачи будут выполняться прямо в запросе.

### 8. Celery не стартует: `No module named 'config'`

**Причина.** Воркер запущен не из корня проекта либо папка не примонтирована.

**Решение.** Проверьте, что воркер видит задачи:

```bash
docker compose exec worker celery -A config inspect registered
```

Ожидаемый вывод — `apps.catalog.tasks.refresh_title_ratings`.
Если пусто: `docker compose restart worker`, затем `docker compose logs worker`.

### 9. `permission denied` при обращении к `media/` или `staticfiles/`

**Причина.** Боевой образ работает от пользователя `app`, а не от root.
Тома, созданные root, ему недоступны.

**Решение.**

```bash
docker compose down -v
docker compose up --build -d
```

В разработке этой ошибки нет: dev-стадия работает от root намеренно,
чтобы примонтированная папка проекта была доступна на запись.

### 10. Образ не собирается: `failed to solve` или обрыв на `pip install`

**Причина.** Нет сети, зеркало PyPI недоступно, либо повреждён кэш слоёв.

**Решение.**

```bash
docker compose build --no-cache web
```

Если не помогло — освободите место (`docker system df`, затем
`docker system prune -a`, осторожно: удалит неиспользуемые образы).

### 11. Swagger открывается пустым или отдаёт 500

**Причина.** Сломана аннотация `@extend_schema` — одна ошибка роняет
сборку схемы целиком.

**Решение.** Посмотрите, что говорит генератор:

```bash
docker compose exec web python manage.py spectacular --file /tmp/schema.yml
```

Он назовёт файл и строку. Схема обязана собираться без предупреждений.

### 12. Сайт открывается, но страницы без стилей

**Причина.** Браузер закэшировал старые CSS.

**Решение.** Обновите страницу с `Ctrl+F5` (Windows) или `Cmd+Shift+R` (macOS).

### 13. Изменил код, а на сайте ничего не поменялось

**Причина.** Папка проекта примонтирована, и сервер перезапускается сам —
но не всегда ловит изменения.

**Решение.** `docker compose restart web`. После изменения `requirements/`
нужна пересборка: `docker compose up --build -d`.

### 14. `Invalid HTTP_HOST header` / ошибка 400 на всё

**Причина.** Домен не указан в `ALLOWED_HOSTS`. Django намеренно отклоняет
запросы с чужим Host — это защита от подмены заголовка.

**Решение.** Локально открывайте `localhost` или `127.0.0.1`. Для другого
домена добавьте его в `DJANGO_ALLOWED_HOSTS` в `.env` через запятую.

### 15. Тесты падают: `database ... is being accessed by other users`

**Причина.** Осталась висящая тестовая база от прерванного прогона.

**Решение.** `docker compose restart db`, затем запустите тесты снова.

---

## Production

Боевое окружение живёт в отдельном файле — `docker-compose.prod.yml`.
Оно отличается от разработки принципиально, а не настройками:

| | Разработка | Бой |
|---|---|---|
| Сервер | `runserver` | Gunicorn, 3 воркера |
| Настройки | `development.py`, `DEBUG=True` | `production.py`, `DEBUG=False` |
| Стадия образа | `development` | `production` |
| Пользователь | root | `app`, без прав root |
| Код | примонтирован с хоста | скопирован в образ |
| Статика | отдаёт Django | `collectstatic` + WhiteNoise |
| Пакеты | + ruff, coverage | только боевые |
| HTTPS | нет | `SECURE_SSL_REDIRECT`, HSTS на год |
| Планировщик | нет | сервис `beat` |

### Запуск

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

Поднимутся пять сервисов: `db`, `redis`, `web`, `worker`, `beat`.
Миграции и `collectstatic` выполнятся автоматически при старте.

### Переменные окружения

Обязательны в `.env`:

```
DJANGO_SECRET_KEY=<длинный случайный ключ, НЕ тот же, что в разработке>
POSTGRES_PASSWORD=<сильный пароль>
DJANGO_ALLOWED_HOSTS=lumibox.example.com,www.lumibox.example.com
```

За обратным прокси (Nginx) добавьте:

```
DJANGO_NUM_PROXIES=1
```

**Это важно для безопасности.** При значении по умолчанию (`0`) ключом
ограничения частоты служит адрес прокси — и все посетители склеятся в один
лимит на всех. Значение `1` говорит DRF брать реальный адрес клиента из
`X-Forwarded-For`. Ставить его нужно **только** если перед приложением
действительно стоит доверенный прокси: иначе клиент подделает заголовок
и обойдёт лимит.

### Проверка перед выкатом

```bash
docker compose -f docker-compose.prod.yml config --quiet
docker compose exec web sh -c 'DJANGO_SETTINGS_MODULE=config.settings.production \
  DJANGO_ALLOWED_HOSTS=example.com python manage.py check --deploy'
```

Обе команды обязаны пройти без замечаний.

### Что ещё нужно для настоящего боя

Проект готов к запуску, но перед выкатом на публичный домен потребуется:

- **Nginx или другой обратный прокси** с TLS-сертификатом. Конфига в проекте
  нет — он зависит от хостинга
- **`client_max_body_size`** в Nginx. Валидатор картинок отбрасывает большой
  файл уже после приёма — трафик потрачен. Настоящий лимит ставится на прокси
- **Резервное копирование** тома `postgres_data`
- **Мониторинг** воркера Celery: сейчас его падение никто не заметит

---

## Запуск без Docker

Понадобится Python 3.13+, PostgreSQL 18 и, по желанию, Redis.

**1. Виртуальное окружение**

```bash
python -m venv .venv

source .venv/bin/activate          # Linux, macOS
.\.venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -r requirements/development.txt
```

**2. База данных**

```bash
psql -U postgres -c "CREATE USER lumibox WITH PASSWORD 'ваш_пароль';"
psql -U postgres -c "CREATE DATABASE lumibox OWNER lumibox;"
```

**3. Переменные окружения**

Скопируйте `.env.example` в `.env`. Укажите `DATABASE_URL` с портом **5432**
(а не 5433 — тот только для базы в Docker) и сгенерируйте ключ:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Redis необязателен: без `REDIS_URL` кэш работает в памяти процесса,
а задачи Celery выполняются прямо в запросе.

**4. Запуск**

```bash
python manage.py migrate
python manage.py seed_catalog
python manage.py createsuperuser
python manage.py runserver
```

---

## Лицензия

Проект распространяется по лицензии **MIT** — полный текст в файле
[LICENSE](LICENSE) в корне репозитория.

Коротко: код можно использовать, копировать, изменять и включать в свои
проекты, в том числе коммерческие. Единственное требование — сохранять
упоминание автора и текст лицензии. Гарантий никаких: программа поставляется
«как есть».

Лицензия покрывает код проекта. Загруженные через админку материалы —
постеры, кадры, видео — ею не покрываются: права на них принадлежат
их правообладателям.

---

## Автор

**Nurullo** — автор и ведущий разработчик.

Дизайн, вёрстка, backend и инфраструктура сделаны с нуля для этого проекта.
Данные о фильмах — общедоступные факты; описания написаны специально
для каталога.
