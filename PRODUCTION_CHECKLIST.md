# Production Checklist — MovieHub

## 🔐 Безопасность

- [ ] `DJANGO_SECRET_KEY` — уникальный ключ, не из .env.example
- [ ] `DJANGO_DEBUG=False`
- [ ] `DJANGO_ALLOWED_HOSTS` — конкретные домены
- [ ] HTTPS включён (SECURE_SSL_REDIRECT=True)
- [ ] HSTS настроен (1 год, include_subdomains, preload)
- [ ] Cookie: Secure, HttpOnly, SameSite=Lax
- [ ] CSP заголовки настроены
- [ ] CORS: только доверенные домены
- [ ] django-axes: 5 попыток, 5 минут кулдаун

## 🗄 База данных

- [ ] PostgreSQL 14+ (не SQLite!)
- [ ] `DATABASE_URL` настроен
- [ ] Connection pooling: CONN_MAX_AGE=600
- [ ] Миграции применены: `python manage.py migrate`
- [ ] Индексы созданы (5 индексов на Title)

## 📦 Кэш и фоновые задачи

- [ ] Redis запущен
- [ ] `REDIS_URL` настроен
- [ ] Celery worker запущен
- [ ] Celery beat запущен (пересчёт рейтингов, публикация по расписанию)

## 🌐 Статика и медиа

- [ ] `python manage.py collectstatic`
- [ ] WhiteNoise настроен (production.py)
- [ ] Медиа-файлы доступны (постеры, кадры)
- [ ] PWA иконки на месте (192, 512)

## 📊 Мониторинг

- [ ] `SENTRY_DSN` настроен
- [ ] `GOOGLE_ANALYTICS_ID` настроен (опционально)
- [ ] `YANDEX_METRIKA_ID` настроен (опционально)
- [ ] Health check: `/healthz/` отвечает 200
- [ ] Логи пишутся в stdout

## 🎬 Контент

- [ ] `python manage.py seed_catalog` — заполнить жанры, страны
- [ ] `python manage.py seed_content` — заполнить фильмы, персоны, отзывы
- [ ] `python manage.py seed_video_assets` — создать видео-ассеты
- [ ] `python manage.py generate_placeholder_art` — генерация заглушек
- [ ] Реальные постеры загружены через админку

## 🚀 Деплой

- [ ] Docker image собран
- [ ] `docker-compose.prod.yml` запущен
- [ ] Nginx настроен (проксирование, кэширование статики)
- [ ] SSL сертификат установлен
- [ ] Домен привязан

## 📱 Фронтенд

- [ ] Service Worker регистрируется
- [ ] PWA manifest доступен
- [ ] Тема (dark/light) работает
- [ ] Языковой переключатель работает (ru/en)
- [ ] Мобильная навигация работает
- [ ] Поиск с автокомплитом работает
- [ ] WebSocket уведомления работают

## ✅ Тесты

```bash
python manage.py check
python manage.py test
ruff check apps config
```

Все должно быть зелёным.
