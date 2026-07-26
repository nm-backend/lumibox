.PHONY: help install migrate seed run test lint check clean docker-up docker-down

help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------- Локальная разработка ----------

install: ## Установить зависимости
	python -m venv .venv
	.venv/bin/pip install -r requirements/development.txt
	@echo "\n✅ Зависимости установлены. Создайте .env: cp .env.example .env"

migrate: ## Применить миграции
	python manage.py migrate

seed: ## Заполнить каталог демо-данными
	python manage.py seed_catalog
	python manage.py seed_content
	python manage.py seed_video_assets

seed-tmdb: ## Импорт из TMDB (нужен TMDB_API_KEY в .env)
	python manage.py import_from_tmdb --count 50 --type both

createsuperuser: ## Создать админа
	python manage.py createsuperuser

run: ## Запустить сервер разработки
	python manage.py runserver

run-celery: ## Запустить Celery worker
	celery -A config worker -l info

run-beat: ## Запустить Celery beat (расписание задач)
	celery -A config beat -l info

# ---------- Качество ----------

test: ## Запустить тесты
	python manage.py test

lint: ## Проверить код (ruff)
	ruff check apps config scripts

format: ## Форматировать код
	ruff format apps config scripts

check: ## Все проверки (lint + check + test)
	python manage.py check
	ruff check apps config
	python manage.py test

# ---------- i18n ----------

messages: ## Собрать переводы
	python manage.py makemessages -l en --no-wrap

compile-messages: ## Скомпилировать переводы
	python manage.py compilemessages

# ---------- Продакшен ----------

collectstatic: ## Собрать статику
	python manage.py collectstatic --noinput

backup: ## Бэкап базы данных
	python manage.py backup_database

# ---------- Docker ----------

docker-up: ## Запустить в Docker (dev)
	docker compose up -d

docker-down: ## Остановить Docker
	docker compose down

docker-prod: ## Запустить в Docker (prod)
	docker compose -f docker-compose.prod.yml up -d

# ---------- Очистка ----------

clean: ## Учистить кэш и временные файлы
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf staticfiles/ htmlcov/ .coverage

# ---------- Быстрый старт ----------

quickstart: install migrate seed createsuperuser run ## Полный запуск с нуля
