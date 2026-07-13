"""
Gunicorn configuration for the VaultIQ backend.

Why this file:
- Centralizes Gunicorn settings instead of using Docker CLI flags.
- Enables `preload_app`, which cannot be configured cleanly from the Docker CMD.

Why `preload_app = True`:
- Loads the Flask app, embedding model, and LLM once in the Gunicorn master
  process before workers are forked.
- Workers share the preloaded model memory using Linux copy-on-write,
  reducing RAM usage and eliminating per-worker cold starts.

Why `post_fork`:
- SQLAlchemy connection pools are not fork-safe.
- Dispose inherited connections after forking so each worker creates its own
  database connections when needed.

Why configurable timeout:
- LLM requests may involve retries and fallback models.
- Timeout is configurable via `GUNICORN_TIMEOUT` to support different
  environments without changing code. 
"""

import os

# Server socket
bind = "0.0.0.0:5000"

# Worker processes
workers = int(os.getenv("GUNICORN_WORKERS", "2"))

# for duplicate model loading
preload_app = True

# Worker killed if request takes longer than this.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "300"))

# Logging
# "-" means stdout/stderr — picked up by rotating file handlers in logging_config.py
# via Python's root logger, and by render's log viewer.
accesslog = "-"
errorlog = "-"

def post_fork(server, worker):
    """
    Runs in each worker process immediately after fork (with preload_app, DB already
    exists in master before this point).
    
    Dispose inherited SQLAlchemy connection pool so this worker opens its own fresh
    connections instead of reusing (potentially corrupting) inherited from master process.
    """
    from wsgi import app
    from extensions import db
    
    with app.app_context():
        db.engine.dispose()
    
    server.log.info(f"Worker {worker.pid}: DB engine pool reset after fork.")
    