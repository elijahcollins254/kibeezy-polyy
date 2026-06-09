Celery setup (quick start)

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Start Redis (local):

```bash
redis-server --port 6379
```

3. Start Django (in one terminal):

```bash
python manage.py migrate
python manage.py runserver
```

4. Start Celery worker (in another terminal):

```bash
celery -A api.celery worker --loglevel=info
```

Optional: enable beat for scheduled tasks:

```bash
celery -A api.celery beat --loglevel=info
```

Notes:
- Configure `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` via environment variables (defaults use `redis://127.0.0.1:6379`).
- Ensure `api/__init__.py` imports the Celery app so `shared_task` uses the right app.
