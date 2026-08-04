"""
WSGI entrypoint for Gunicorn (Docker production only).

Why this file:
- Keeps `app.py` lightweight so tests can import it without triggering
  database initialization or loading ML models.
- Performs startup tasks that should run only in a real Gunicorn process.

Startup sequence:
1. Import the Flask application.
2. Development-only convenience: create SQLite tables if they don't exist
   yet. Production (APP_ENV=production) never runs db.create_all() — schema
   there is managed exclusively by Alembic migrations.
3. Warm up the embedding model and LLM.

With `preload_app = True` (see gunicorn.conf.py), the warm-up runs once in
the Gunicorn master process. Worker processes then share the preloaded model
memory via Linux copy-on-write, reducing memory usage and eliminating
per-worker cold starts.

Usage (see gunicorn.conf.py and Dockerfile CMD):
    gunicorn --config gunicorn.conf.py wsgi:app
"""
import logging

from app import app  # noqa: F401  # Exposed for Gunicorn (wsgi:app)
from config import APP_ENV
from extensions import db
from services import _get_embedding_model, _get_llm

logger = logging.getLogger(__name__)

if APP_ENV == "development":
  # Covers the case where someone runs `gunicorn wsgi:app` locally instead of `python app.py` — 
  # same SQLite-schema convenience, kept out of production where Alembic owns the schema.
  with app.app_context():
    db.create_all()
    logger.info("Database tables verified/created.")
    
# Eager model warm-up (run once, in gunicorn master process)
logger.info("Warming up embedding model and LLM client before fork...")
_get_embedding_model()
_get_llm()
logger.info("Warm-up complete. Workers will share this via copy-on-write.")
