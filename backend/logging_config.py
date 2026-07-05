"""
Logging Configuration
=====================
Writes logs to both stdout and rotating log files simultaneously.

Features:
* Logs are written to the console and persistent files simultaneously.
* Uses rotating file handlers (5 MB per file, 5 backups each).
* Supports long-term debugging, auditing, and error tracking.

Log Files:
* app.log     : General application activity (INFO and above)
* error.log   : Warnings, errors, and exceptions (WARNING and above)
* access.log  : HTTP request/response logs (Werkzeug)

Storage:
* Logs are stored in backend/storage/logs/.
* When using persistent storage (e.g., Render Persistent Disk), logs survive redeployments and restarts.
* On ephemeral storage, logs remain available only for the lifetime of the running container.

Usage:
from logging_config import setup_logging
setup_logging()   # Call once during application startup

```
import logging
logger = logging.getLogger(__name__)
logger.info("...")
```
"""
import logging
import logging.handlers
import os
import sys

from config import LOG_LEVEL, LOG_DIR

# Rotation settings
MAX_BYTES       = 5 * 1024 * 1024   # 5MB
BACKUP_COUNT    = 5

def _make_rotating_handler(filename: str, level: int) -> logging.handlers.RotatingFileHandler:
    """
    Create a RotatingFileHandler for the given filename.

    Rotating means: once the file hits MAX_BYTES, it's renamed to
    app.log.1, app.log.2 ... app.log.5 and a fresh file starts.
    Files beyond BACKUP_COUNT are deleted automatically.
    This bounds total disk usage regardless of how long the app runs.
    """
    path = os.path.join(LOG_DIR, filename)
    handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    return handler


def setup_logging():
    """
    Configure root logging once at application startup.
    
    Attaches three handlers to the root logger:
        stdout       — all logs (mirrors what you see in terminal / Render UI)
        app.log      — INFO+ (general activity, rotating)
        error.log    — WARNING+ (failures only, rotating)
        
    werkzeug's access log is captured separately into access.log.
    
    Format:
        2026-06-16 10:42:11 INFO     rag_service: Detected query type: 'summarize'    
    """
    
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # Root logger
    root = logging.getLogger()
    root.setLevel(level)
    
    # Remove any handlers attached by earlier basicconfig calls
    root.handlers.clear()
    
    # Handler 1 — stdout (keeps terminal + render ui working)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.setFormatter(fmt)
    root.addHandler(stdout_handler)    
    
    # Handler 2 — app.log (INFO+, rotating)
    app_handler = _make_rotating_handler("app.log", logging.INFO)
    app_handler.setFormatter(fmt)
    root.addHandler(app_handler)   
    
    # Handler 3 — error.log (WARNING+ only — easy to grep for failures)
    error_handler = _make_rotating_handler("error.log", logging.WARNING)
    error_handler.setFormatter(fmt)
    root.addHandler(error_handler)
    
    # Werkzeug access log (HTTP requests)
    # Werkzeug logs every request as INFO — we capture it into access.log
    # separately so HTTP traffic doesn't drown out application logs in app.log.
    access_handler = _make_rotating_handler("access.log", logging.INFO)
    access_handler.setFormatter(fmt)
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.propagate = False   # dont also send to root (app.log)
    werkzeug_logger.addHandler(access_handler)
    werkzeug_logger.addHandler(stdout_handler)  # still show in terminal
    
    # Silence noisy third-party libraries
    # These log at DEBUG/INFO by default and drown out application logs.
    for noisy_lib in ("httpx", "chromadb", "sentence_transformers", "urllib3"):
        logging.getLogger(noisy_lib).setLevel(logging.WARNING)
    
    logging.getLogger(__name__).info(f"Logging configured | level={LOG_LEVEL} | log_dir={LOG_DIR}")
    logging.getLogger(__name__).info(f"Log files: app.log (INFO+), error.log (WARNING+), access.log (HTTP)")
    