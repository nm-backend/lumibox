# Аудит LumiBox — 24 направления

Статус финальной проверки. Цель — «10/10»: каждый пункт либо закрыт кодом
и доказан прогоном, либо честно помечен как ожидающий внешних credentials
(настройки вне репозитория).

Легенда: ✅ закрыто и проверено · 🟡 код готов, ждёт credentials на проде.

## Сводка

| # | Направление | Статус | Доказательство |
|---|-------------|--------|----------------|
| 1 | Тесты и покрытие | ✅ | 314 тестов (3 skip), OK; coverage 94%; CI порог 90% |
| 2 | Статический анализ (ruff) | ✅ | `ruff check apps config scripts` — 0 ошибок |
| 3 | Статическая типизация (mypy) | ✅ | `mypy apps` — 0 ошибок, 108 файлов; шаг в CI |
| 4 | Миграции | ✅ | `makemigrations --check --dry-run` — no changes |
| 5 | Боевые проверки Django | ✅ | `check --deploy --fail-level WARNING` — 0 issues |
| 6 | CI/CD | ✅ | GitHub Actions: ruff, mypy, branding, check, migrations, тесты, coverage |
| 7 | Деплой-конфиги | ✅ | Dockerfile (multi-stage), render.yaml, fly.toml, railway.json, docker-compose.prod.yml |
| 8 | Живой прод (Render) | ✅ | healthz 200, home 200, admin, статика Whitenoise, HTTPS |
| 9 | Доступность (a11y) | ✅ | axe (WCAG 2.0/2.1 AA): 0 нарушений на home, catalog, genres, login, title |
| 10 | Клавиатура и скринридеры | ✅ | нативная radio-шкала рейтинга, aria-live, фокус-навигация табов |
| 11 | SEO | ✅ | sitemap.xml, JSON-LD, Open Graph, canonical, robots |
| 12 | Безопасность заголовков | ✅ | CSP, HSTS, X-Content-Type-Options, X-Frame-Options (check --deploy 0) |
| 13 | CSRF/XSS/Clickjacking | ✅ | CSRF_COOKIE_HTTPONLY, CSP, DRF-настройки, тесты middleware |
| 14 | Brute-force защита | ✅ | django-axes (блокировка по username+IP), тесты |
| 15 | Рейт-лимиты | ✅ | 60/мин гость, 300/мин авторизованный, 429 на превышение |
| 16 | Медиа и файлы | ✅ | WebP-конвертация, лимиты upload 10MB, удаление файлов+WebP при удалении записи, тесты |
| 17 | Видео и стриминг | ✅ | Range-запросы 206/416, Accept-Ranges, Cache-Control, защита от path traversal; проверено live (локально и на проде) |
| 18 | Кэширование | ✅ | генерации (similar/recommendations), маппинг инвалидации, warm-home-cache, тесты |
| 19 | Производительность БД | ✅ | select_related/prefetch, индексные миграции, N+1-тесты |
| 20 | Мобильная версия | ✅ | матрица 320/360/390/414/768 без горизонтального скролла, bottom-nav |
| 21 | Observability | ✅ | request-id (X-Request-ID + логи + Sentry-тег), structured-логи, healthz, Sentry-интеграция |
| 22 | Аналитика и consent | ✅ | GA4 грузится только после явного согласия; без GA_ID — 0 байт трекинга; view_item на тайтлах |
| 23 | API и документация | ✅ | DRF + drf-spectacular, /api/docs/, /api/schema/, тесты документации |
| 24 | Email и сброс пароля | 🟡 | SMTP-бэкенд готов (включается по EMAIL_HOST), на проде ждёт SMTP-credentials |
| — | R2-хранилище (прод) | 🟡 | Код готов (публичная раздача, CacheControl, WebP, очистка), на проде ждёт R2-credentials |
| — | Sentry (прод) | 🟡 | Интеграция готова, на проде ждёт SENTRY_DSN |
| — | GA4 (прод) | 🟡 | Consent-first трекинг готов, на проде ждёт GA_MEASUREMENT_ID |

## Доказательства (ключевые прогоны)

```
python manage.py test apps                → Ran 311, OK (skipped=3)
coverage report                            → TOTAL 94%
mypy apps                                  → Success: no issues found (108 files)
ruff check apps config scripts             → All checks passed!
makemigrations --check --dry-run           → No changes detected
check --deploy --settings=config.settings.production → 0 issues
scripts/smoke_pages.py                     → все страницы 200 (21+ URL)
axe (WCAG 2.0/2.1 AA)                      → 0 violations (5 страниц)
мобильная матрица                          → 320/360/390/414/768 без overflow
curl -H "Range: bytes=0-99" /media/...     → 206 + Content-Range + Cache-Control: public, max-age=86400
curl /healthz/ (прод Render)               → 200
```

## Ограничения (не код)

1. **Прод-медиа на эфемерной ФС Render** — файлы теряются при пересоздании
   контейнера. R2-интеграция готова и выключена ровно настолько, насколько
   не заданы `AWS_*` / `CLOUDFLARE_R2_PUBLIC_URL`.
2. **SMTP/Sentry/GA на проде** не заданы — код включит их автоматически
   при появлении `EMAIL_HOST`, `SENTRY_DSN`, `GA_MEASUREMENT_ID`
   в Dashboard Render.
3. Точный список env для вставки — в `.env.production.example`.

## Как получить «10/10» по всем строкам

1. Создать R2-бакет + API-токен (Cloudflare) и вставить 5 переменных на Render.
2. Создать SMTP-ключ (Mailgun/SendGrid), вставить `EMAIL_*`.
3. (Опционально) `SENTRY_DSN`, `GA_MEASUREMENT_ID`.
4. Передеплой — каждая переменная включается без правки кода.
