# Sentimentri Backend

This repository contains the Sentimentri Django API and the standalone worker service.

## Layout

- `backend/` is the Django REST API, admin portal API, and Celery task worker.
- `worker_service/` is the standalone FastAPI/Celery service.

## Django API

Requirements: Python 3.12+, PostgreSQL, and Redis.

From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements\base.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py runserver
```

Configure database, Redis, Django signing key, allowed hosts, and third-party API credentials in `.env`. Never commit the populated file. The API is served at `http://localhost:8000` by default.

## Standalone worker service

Install `worker_service/requirements.txt`, configure `worker_service/.env.example` as a local `.env`, and run the service from the `worker_service/` directory. Its Dockerfile is also located there.

The root `.env.example` and worker template contain placeholders only. Replace them with local values; use unique, randomly generated secrets outside development.
