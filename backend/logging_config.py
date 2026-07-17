"""
Logging Configuration
=====================
Structured JSON logging for production observanility.

WHY JSON instead of plain text:
    Plain text logs ("2026-07-13 10:00:00 INFO app: something happened") are fine to eyeball in a terminal
    but hard to search, filter, or feed into any log aggregation/analysis tool — even just `jq`/`grep` on raw file.
    JSON logs are one parseable object per line, so any field (request_id, user_id, status, processing_time_ms) 
    can be queried directly instead of regex-ing free text.
    
Features:
* Logs are written to the console and persistent files simultaneously.
* Uses rotating file handlers (5 MB per file, 5 backups each).
* Supports long-term debugging, auditing, and error tracking.

Log Files:
* app.log     : General application activity (INFO and above)
* error.log   : Warnings, errors, and exceptions (WARNING and above)
* access.log  : Structured per=request completion logs + raw Werkzeug HTTP lines

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
logger.info("plain message")

# Structured extra fields (merged into JSON output automatically):
logger.info("PDF ingested", extra={"pdf_filename": "notes.pdf", "chunks": 42})
```
"""
import logging
import logging.handlers
import os
import sys
import json
import warnings
from datetime import datetime, timezone

from config import LOG_LEVEL, LOG_DIR

# Production warnings
# Suppress known, safe third-party warnings that clutter production logs.
# Keep filters targeted so warnings from our own code are still visible.
# Any unfiltered warnings are captured by Python's logging system and
# written as structured logs instead of raw stderr output.
def _configure_warning_filters():
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="langchain_community")
    warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*langchain-community.*")
    warnings.filterwarnings("ignore", category=UserWarning, module="chromadb")
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="jwt")
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="sqlalchemy")
    
    try:
        from sqlalchemy.exc import LegacyAPIWarning
        warnings.filterwarnings("ignore", category=LegacyAPIWarning)
    except ImportError:
        pass
    
    try:
        from jwt.warnings import InsecureKeyLengthWarning
        warnings.filterwarnings("ignore", category=InsecureKeyLengthWarning)
    except ImportError:
        pass
    
    warnings.filterwarnings("ignore", category=UserWarning, module="jwt")

# Rotation settings
MAX_BYTES       = 5 * 1024 * 1024   # 5MB
BACKUP_COUNT    = 5

# Standard attributes every LogRecord carries by default. Anything a
# caller attaches beyond this set (via logger.info(..., extra={...}))
# is treated as a custom structured field and merged into the JSON
# output. Keeping this list explicit means we never accidentally
# swallow or duplicate a field.
_STANDARD_LOG_RECORD_ATTS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName", 
    "created", "msecs", "relativeCreated", "thread", "threadName", "processName",
    "process", "message", "asctime", "taskName", "request_id", "user_is", #ingested by RequestContextFilter
}


class RequestContextFilter(logging.Filter):
    # Attaches request_id + user_id to every LogRecord that passes through root logger,
    # pulled from Flask's request-scoped `g` obj when a request context currently active.
    
    # Both fields are None when there's no active request (e.g. startup/warm-up logs in wsgi.py or any background work) — 
    # expected and correct, not a bug
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            from flask import g, has_request_context
            if has_request_context():
                record.request_id = getattr(g, "request_id", None)
                record.user_id = getattr(g, "user_id", None)
            else:
                record.request_id = None
                record.user_id = None
        except RuntimeError:
            # From app context genuinely not available (e.g. very easily startup, before app obj exists at all)
            record.request_id = None
            record.user_id = None
        return True
        
class JsonFormatter(logging.Formatter):
    # Formats each LogReocrd as a single JSON obj per line
    
    # Always include: timestamp, level, logger, message, request_id, user_id, module, filename, line
    
    # Also merges in any extra structured fields caller passed via logger.info(msg, extra={"key": value}) — e.g. endpoint, 
    # processing_time_ms, status, pdf_filename — so callers can attach whatever's relevant to that specific log line without changing formatter.
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp":    datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level":        record.levelname,
            "logger":       record.name,
            "message":      record.getMessage(),
            "request_id":   getattr(record, "request_id", None),
            "user_id":      getattr(record, "user_id", None),
            # Source-cod provenance — which file/module/line emitted this.
            # Distinct from any "pdf_filename" an ingestion log line might also carry
            # via extra={} — this is about CODE, not a PDF
            "module":       record.module,
            "filename":     record.filename,
            "line":         record.lineno,
        }

        # Merge any caller-supplied extra={}  fields not already covered above
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_ATTS or key in payload or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except TypeError:
                payload[key] = str(value)
                
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


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
        stdout       — all logs (mirrors what you see in terminal / Render / VPS journal)
        app.log      — INFO+ (general activity, rotating)
        error.log    — WARNING+ (failures only, rotating)
        
    werkzeug's access log is captured separately into access.log, alongside structured per-request completion
    lines logged by app.py's after_request (app.py — logger name "http.access")
    
    Format:
        Every line is a single JSON object with, at minimum:
        timestamp, level, logger, message, request_id, user_id,
        module, filename, line
    plus whatever extra fields that specific call site attached.    
    """
    
    # Apply warning filters before importing libraries that may emit them.
    _configure_warning_filters()
    
    # Send any unfiltered warnings through the structured logging pipeline instead of printing them to stderr.
    logging.captureWarnings(True)
    
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    fmt = JsonFormatter()
    request_context_filter = RequestContextFilter()
    
    # Root logger
    root = logging.getLogger()
    root.setLevel(level)
    
    # Remove any handlers attached by earlier basicconfig calls
    root.handlers.clear()
    
    # Handler 1 — stdout (keeps terminal + render UI / VPS journal working)
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
    
    # request_id/user_id are injected via a filter attached to the root logger, 
    # so every handler above (stdout, app.log, error.log) gets them on every record, 
    # regardless of which module logged it.
    root.addFilter(request_context_filter)
    
    # Werkzeug access log (HTTP requests)
    # Werkzeug logs every request as INFO — we capture it into access.log
    # separately so HTTP traffic doesn't drown out application logs in app.log.
    access_handler = _make_rotating_handler("access.log", logging.INFO)
    access_handler.setFormatter(fmt)
    access_handler.addFilter(request_context_filter)
    
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.propagate = False   # dont also send to root (app.log)
    werkzeug_logger.addHandler(access_handler)
    werkzeug_logger.addHandler(stdout_handler)  # still show in terminal
    
    # Structured per-request logger used by app.py's after_request hook.
    # Writes to SAME access.log file as werkzeug's raw lines, but each line is fully structured
    # JSON object with explicit fields.
    http_access_logger = logging.getLogger("http.access")
    http_access_logger.propagate = False
    http_access_logger.addHandler(access_handler)
    http_access_logger.addHandler(stdout_handler)
    http_access_logger.setLevel(logging.INFO)
    
    # Silence noisy third-party libraries
    # These log at DEBUG/INFO by default and drown out application logs.
    for noisy_lib in ("httpx", "chromadb", "sentence_transformers", "urllib3"):
        logging.getLogger(noisy_lib).setLevel(logging.WARNING)
    
    logging.getLogger(__name__).info(f"Logging configured | level={LOG_LEVEL} | log_dir={LOG_DIR} | format=json")
    logging.getLogger(__name__).info(f"Log files: app.log (INFO+), error.log (WARNING+), access.log (structured per-request + raw werkzeug HTTP)")
    