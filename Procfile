# Для платформ на базе Procfile (Railway/Heroku-совместимые, Koyeb).
# release идёт до старта: миграции и сборка статики (на buildpack-платформах
# без Docker статику собрать больше негде). Под Docker статика уже в образе,
# повторный collectstatic безвреден и идемпотентен.
release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
web: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 60
worker: celery -A config worker -B -l info
