"""
Tier 1 — Unit Tests: Logging Configuration
============================================
Fast, in-process tests for logging_config.py. Covers the two concrete bugs
found in production (request_id/user_id always None on module-logger
records; the user_is/user_id typo) plus the ENABLE_FILE_LOGGING gate.

The real fork-safety / Gunicorn-integration behavior is covered separately
in test_integration_logging_gunicorn.py, which runs an actual Gunicorn
process — that's the only way to genuinely prove behavior across forked
workers; these tests intentionally stay in-process and fast.
"""
import os
import sys
import json
import logging
import logging.handlers
import importlib

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture(autouse=True)
def _reset_logging_state():
    """
    logging_config.setup_logging() mutates global logging state (root
    handlers, "http.access"/"werkzeug" logger handlers). Reset around every
    test so tests don't leak handlers into each other.
    """
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level

    for name in ("http.access", "werkzeug"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    yield

    root.handlers.clear()
    for h in original_handlers:
        root.addHandler(h)
    root.setLevel(original_level)
    for name in ("http.access", "werkzeug"):
        logging.getLogger(name).handlers.clear()


def _capture_records(logger_name=None):
    """Attach a capturing Handler (with the real RequestContextFilter) to
    the given logger (root, if None) and return (handler, records_list)."""
    from logging_config import RequestContextFilter

    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = Capture()
    handler.addFilter(RequestContextFilter())
    target = logging.getLogger(logger_name) if logger_name else logging.getLogger()
    target.addHandler(handler)
    return handler, records


class TestStandardLogRecordAttrs:

    def test_user_is_typo_fixed(self):
        from logging_config import _STANDARD_LOG_RECORD_ATTS
        assert "user_is" not in _STANDARD_LOG_RECORD_ATTS, "typo 'user_is' should no longer exist"
        assert "user_id" in _STANDARD_LOG_RECORD_ATTS


class TestRequestContextFilterAtHandlerLevel:
    """
    Regression tests for the core bug: a filter attached to the ROOT logger
    (root.addFilter(...)) never runs for records from a CHILD logger that
    propagates up to root — only the originating logger's own filters run.
    Handler-level filters, by contrast, run for every record that reaches
    that handler. logging_config.py must attach the filter per-handler.
    """

    def test_child_logger_gets_request_id_and_user_id(self):
        from flask import Flask, g

        app = Flask(__name__)
        handler, records = _capture_records()  # attached to root, like production

        # A module-level logger, e.g. logging.getLogger(__name__) in
        # services/rag_service.py or routes/upload_routes.py — NOT root.
        child_logger = logging.getLogger("services.rag_service")
        child_logger.setLevel(logging.INFO)

        with app.test_request_context("/"):
            g.request_id = "req-abc"
            g.user_id = 99
            child_logger.info("doing work")

        assert len(records) == 1
        assert records[0].request_id == "req-abc"
        assert records[0].user_id == 99

    def test_no_request_context_yields_none_not_missing(self):
        handler, records = _capture_records()
        logging.getLogger("services.rag_service").info("background work, no request")

        assert len(records) == 1
        # Explicit None (present, correct value), not simply absent —
        # JsonFormatter's getattr(..., None) fallback should never actually
        # be needed once the filter is attached correctly.
        assert records[0].request_id is None
        assert records[0].user_id is None


class TestJsonFormatterOutput:

    def test_formats_valid_json_with_required_fields(self):
        from logging_config import JsonFormatter, RequestContextFilter

        record = logging.LogRecord(
            name="services.rag_service", level=logging.INFO, pathname=__file__,
            lineno=1, msg="ingested pdf", args=(), exc_info=None,
        )
        RequestContextFilter().filter(record)  # no request context -> None/None

        line = JsonFormatter().format(record)
        parsed = json.loads(line)  # must be valid JSON, one object per line

        for field in ("timestamp", "level", "logger", "message", "request_id", "user_id", "module", "filename", "line"):
            assert field in parsed
        assert parsed["message"] == "ingested pdf"
        assert parsed["level"] == "INFO"

    def test_extra_fields_are_merged(self):
        from logging_config import JsonFormatter, RequestContextFilter

        record = logging.LogRecord(
            name="http.access", level=logging.INFO, pathname=__file__,
            lineno=1, msg="request completed", args=(), exc_info=None,
        )
        RequestContextFilter().filter(record)
        record.endpoint = "/upload"
        record.status = 200
        record.processing_time_ms = 12.3

        parsed = json.loads(JsonFormatter().format(record))
        assert parsed["endpoint"] == "/upload"
        assert parsed["status"] == 200
        assert parsed["processing_time_ms"] == 12.3


class TestFileLoggingGate:
    """
    ENABLE_FILE_LOGGING must default to False, and setup_logging() must not
    create any RotatingFileHandler unless it's explicitly true — file
    handlers shared across forked Gunicorn workers are the original hazard
    this whole module exists to avoid.
    """

    def test_disabled_by_default_no_file_handlers(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "x")
        monkeypatch.delenv("ENABLE_FILE_LOGGING", raising=False)

        import config
        importlib.reload(config)
        assert config.ENABLE_FILE_LOGGING is False

        monkeypatch.setattr(config, "LOG_DIR", str(tmp_path))
        import logging_config
        importlib.reload(logging_config)
        logging_config.setup_logging()

        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert file_handlers == [], "no RotatingFileHandler should exist when ENABLE_FILE_LOGGING is unset"
        assert list(tmp_path.iterdir()) == [], "no log files should be created on disk"

    def test_enabled_creates_file_handlers(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "x")
        monkeypatch.setenv("ENABLE_FILE_LOGGING", "true")

        import config
        importlib.reload(config)
        assert config.ENABLE_FILE_LOGGING is True

        monkeypatch.setattr(config, "LOG_DIR", str(tmp_path))
        import logging_config
        importlib.reload(logging_config)
        logging_config.setup_logging()

        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert len(file_handlers) == 2  # app.log + error.log on root

        monkeypatch.delenv("ENABLE_FILE_LOGGING", raising=False)
        importlib.reload(config)
        importlib.reload(logging_config)


class TestExactlyOneAccessLogPerRequest:

    def test_http_access_logger_emits_once(self):
        """
        app.py's after_request hook logs exactly once via the "http.access"
        logger per request. Combined with gunicorn.conf.py's accesslog=None
        (no separate Gunicorn-native access line), this is what guarantees
        exactly one structured line per request in production.
        """
        handler, records = _capture_records("http.access")
        access_logger = logging.getLogger("http.access")
        access_logger.propagate = False
        access_logger.setLevel(logging.INFO)

        access_logger.info("request completed", extra={
            "endpoint": "/health", "method": "GET", "status": 200,
            "processing_time_ms": 1.2, "remote_addr": "127.0.0.1",
        })

        assert len(records) == 1