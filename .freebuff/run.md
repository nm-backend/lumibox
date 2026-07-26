# Run doc — MovieHub (thms1udq1k5wv4)

## How to reproduce artifacts

1. **Environment**: Copy `.env` from the main checkout:
   ```
   cp /c/Users/User/Documents/GitHub/moviehub-app/.env /c/Users/User/Documents/GitHub/moviehub-app/.freebuff/worktrees/thms1udq1k5wv4/.env
   ```
2. **Virtual environment**: The venv is at `.venv/` inside the worktree. If missing, create it:
   ```
   cd /c/Users/User/Documents/GitHub/moviehub-app/.freebuff/worktrees/thms1udq1k5wv4
   python -m venv .venv
   source .venv/Scripts/activate  # or .venv/bin/activate on Linux
   pip install -r requirements/development.txt
   ```
3. **Database**: The project uses SQLite locally. Run migrations:
   ```
   cd /c/Users/User/Documents/GitHub/moviehub-app/.freebuff/worktrees/thms1udq1k5wv4
   python manage.py migrate
   ```
4. **Seed data** (optional, gives demo content):
   ```
   python manage.py seed_catalog
   ```

## How to run the server

```
cd /c/Users/User/Documents/GitHub/moviehub-app/.freebuff/worktrees/thms1udq1k5wv4
python manage.py runserver 0.0.0.0:9000 &
```

The server listens on **port 9000** (default for this project). Verify it's up:

```
curl http://127.0.0.1:9000/
```

The log file is at:
```
C:\Users\User\Documents\GitHub\moviehub-app\.freebuff\preview-thms1udq1k5wv4.log
```
