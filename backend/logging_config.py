"""
Logging Configuration
=====================
Structured JSON logging for Docker + Gunicorn deployments.

Design:
- JSON logs provide searchable fields such as request_id, user_id, status,
  and processing_time_ms.
- stdout (INFO+) and stderr (WARNING+) are the authoritative production
  destinations and are captured by Docker's logging driver.
- Rotating file logging is disabled by default because RotatingFileHandler
  is not process-safe across forked Gunicorn workers. It is available only
  as an opt-in for local single-process debugging via ENABLE_FILE_LOGGING.
- RequestContextFilter is attached to each handler, not the root logger,
  ensuring request_id/user_id are added to records from all child loggers.
- http.access emits one structured completion record per request; Gunicorn
  access logging is disabled to avoid duplicate access logs.

Streams:
    stdout      INFO+ application and access logs (JSON)
    stderr      WARNING+ errors and exceptions (JSON)
    files       Optional local-dev rotating logs only

Usage:
from logging_config import setup_logging
setup_logging()   # Call once during application startup

import logging
logger = logging.getLogger(__name__)
logger.info("plain message")
# Structured extra fields (merged into JSON output automatically):
logger.info("PDF ingested", extra={"pdf_filename": "notes.pdf", "chunks": 42})
"""
import logging
import logging.handlers
import os
import sys
import json
import warnings
from datetime import datetime, timezone

from config import LOG_LEVEL, LOG_DIR, ENABLE_FILE_LOGGING

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

# Rotation settings (only relevant when ENABLE_FILE_LOGGING=true)
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
    "process", "message", "asctime", "taskName", "request_id", "user_id", #ingested by RequestContextFilter
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
    
    # Handler 1 — stdout — authoritative, INFO+
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.setFormatter(fmt)
    stdout_handler.addFilter(request_context_filter)
    root.addHandler(stdout_handler)   
    
    # Handler 2: stderr — authoritative, WARNING+ only
    # Gives "error.log"-equivalent stream without shared file: anyone tailing/greping
    # container's stderr sees failures only.
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(fmt)
    stderr_handler.addFilter(request_context_filter)
    root.addFilter(stderr_handler)
    
    all_handlers = [stdout_handler, stderr_handler]
    
    # Optional file handlers (local dev only)
    if ENABLE_FILE_LOGGING:
        app_file_handler = _make_rotating_handler("app.log", logging.INFO)
        app_file_handler.setFormatter(fmt)
        app_file_handler.addFilter(request_context_filter)
        root.addHandler(app_file_handler)   

        error_file_handler = _make_rotating_handler("error.log", logging.WARNING)
        error_file_handler.setFormatter(fmt)
        error_file_handler.addFilter(request_context_filter)
        root.addHandler(error_file_handler)
    
        all_handlers.extend([app_file_handler, error_file_handler])
    
    
    # Werkzeug access log (HTTP requests) — only fires when using Werkzeug's dev server 
    # (flask run / app.run()), never under gunicorn, whih handles WSGI protocol itself 
    # without going through werkzeug's request logging at all.  
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.propagate = False   # dont also send to root
    werkzeug_logger.setLevel(logging.INFO)
    werkzeug_logger.addHandler(stdout_handler)
    
    # Structured per-request logger used by app.py's after_request hook.
    # This is SOLE source of per-request access logging in prod — gunicorn's own 
    # accesslog is disabled so there is exactly one structured line per request here.
    http_access_logger = logging.getLogger("http.access")
    http_access_logger.propagate = False
    http_access_logger.setLevel(logging.INFO)
    http_access_logger.addHandler(stdout_handler)
    
    if ENABLE_FILE_LOGGING:
        access_file_handler = _make_rotating_handler("access.log", logging.INFO)
        access_file_handler.setFormatter(fmt)
        access_file_handler.addFilter(request_context_filter)
        http_access_logger.addFilter(access_file_handler)
        all_handlers.append(access_file_handler)
    
    # Silence noisy third-party libraries
    # These log at DEBUG/INFO by default and drown out application logs.
    for noisy_lib in ("httpx", "chromadb", "sentence_transformers", "urllib3"):
        logging.getLogger(noisy_lib).setLevel(logging.WARNING)
    
    logging.getLogger(__name__).info(
        f"Logging configured | level={LOG_LEVEL} | format=json| "
        f"destination={'stdout/stderr + files' if ENABLE_FILE_LOGGING else 'stdout/stderr only'}"                                 
    )
    if ENABLE_FILE_LOGGING:
        logging.getLogger(__name__).warning(
            "ENABLE_FILE_LOGGING=true: writing rotating log files. This is only safe for a "
            "single-process (non-Gunicorn) run — do NOT enable this under Gunicorn/Docker with "
            "more than one worker, since RotatingFileHandler is not safe across forked processes."
        )
    
    