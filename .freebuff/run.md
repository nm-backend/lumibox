# Run LumiBox preview server

## How to reproduce uncommitted artifacts

This project needs:
1. `.env` file — copy from the main checkout root, which is one level up from `.freebuff/`:
   ```
   copy C:\Users\User\Documents\GitHub\moviehub-app\.env C:\Users\User\Documents\GitHub\moviehub-app\.freebuff\worktrees\thms2w751alp3x\.env
   ```
   (The `.env` is gitignored and lives at the repo root.)

2. Python dependencies — install from the main checkout:
   ```
   cd C:\Users\User\Documents\GitHub\moviehub-app
   python -m venv .venv
   .venv\Scripts\pip install -r requirements\base.txt
   ```

3. Database — SQLite file `db.sqlite3` lives at the repo root and is already present.

## How to run the server

```bash
cd C:\Users\User\Documents\GitHub\moviehub-app
python manage.py runserver 0.0.0.0:8000
```

The server listens on port 8000 (Django default) because the app's own `runserver` command binds there.
