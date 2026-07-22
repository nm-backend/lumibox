# Общая основа для всех вариантов сборки.
FROM python:3.13-slim AS base

# Не писать .pyc и не буферизовать вывод — логи должны попадать
# в stdout сразу, а не когда заполнится буфер.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# libpq5 нужен psycopg во время работы. fonts-dejavu-core (~1 МБ) даёт
# кириллический TTF-шрифт — им команда generate_placeholder_art рисует
# оригинальные постеры-заглушки. Заголовки и компилятор — только на этапе
# сборки, в рабочий образ они не попадут.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libpq5 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*


# ---------- Сборка зависимостей ----------
FROM base AS builder

RUN apt-get update \
    && apt-get install --no-install-recommends -y gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Сначала только зависимости: слой пересоберётся лишь при их изменении,
# а не на каждую правку кода.
COPY requirements/ requirements/
RUN pip install --no-cache-dir --prefix=/install -r requirements/production.txt


# ---------- Локальная разработка ----------
FROM base AS development

ENV DJANGO_SETTINGS_MODULE=config.settings.development

RUN apt-get update \
    && apt-get install --no-install-recommends -y gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/development.txt

# Код не копируем: compose примонтирует папку проекта,
# и правки будут видны без пересборки образа.
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]


# ---------- Боевой образ ----------
FROM base AS production

ENV DJANGO_SETTINGS_MODULE=config.settings.production

COPY --from=builder /install /usr/local

# Отдельный пользователь: процесс в контейнере не должен работать от root.
RUN useradd --create-home --shell /bin/bash app
COPY --chown=app:app . .

# Каталоги статики и медиа создаём и отдаём пользователю app заранее: сам
# /app принадлежит root, и collectstatic под app иначе не смог бы создать
# в нём /app/staticfiles («Permission denied»).
RUN mkdir -p /app/staticfiles /app/media && chown app:app /app/staticfiles /app/media

USER app

# Собираем статику прямо в образ. На платформах вроде Render файловая система
# web-сервиса эфемерна, а предзапусковые команды выполняются в отдельном
# контейнере — собранная там статика до рантайма не доживёт. Значения
# окружения здесь фиктивные и нужны лишь чтобы импортировались настройки:
# collectstatic ни к базе, ни к Redis не обращается.
RUN DJANGO_SECRET_KEY=build-only-not-a-secret \
    DJANGO_ALLOWED_HOSTS=localhost \
    DATABASE_URL=postgres://build:build@localhost:5432/build \
    python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
