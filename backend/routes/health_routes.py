"""
Health Check Route
==================
WHY EXISTS:
     Render (and any CI smoke test) needs a way to confirm the app actually
    booted and its dependencies are reachable — without that, a "successful"
    deploy can still be silently broken (e.g. DB file not writable, Chroma
    path missing). This gives three levels of detail:
 
    /health        — fast, no I/O to Chroma/LLM. Confirms Flask itself is
                      alive and DB is reachable. This is what Render's
                      health-check / uptime monitor should poll frequently.
    /health/deep   — also checks the Chroma path is accessible and (if
                      requested) does a lightweight LLM connectivity check.
                      NOT polled frequently — a real LLM call costs quota
                      on free-tier hosted APIs, so this is for manual/CI
                      checks only, not a load balancer's heartbeat.
 
    Splitting these matters: a load balancer hitting /health every few
    seconds should never burn your Gemini/Groq free-tier quota.
"""
import os
import logging

from flask import Blueprint, jsonify

from config import (
    CHROMA_DB_PATH, 
    SQLITE_DB_PATH, 
    LLM_PROVIDER, 
    LLM_MODEL,
    LOG_DIR
)
from extensions import db

logger = logging.getLogger(__name__)

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
def health():
    """
    Lightweight health check — Flask app _ DB connectivity only.
    Safe to poll frequency (e.g. every 10-30s) from Render or an uptime monitor.
    """
    checks = {"flask": "ok"}
    status_code = 200
    
    # DB check — run a trivial query to confirm the connection actually works,
    # not just that the file exists.
    try:
        db.session.execute(db.text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        logger.error(f"Health check: database failed: {e}")
        checks["database"] = f"error: {e}"
        status_code = 503
        
    return jsonify({
        "status": "ok" if status_code == 200 else "degraded",
        "checks": checks
    }), status_code


@health_bp.route("/health/deep", methods=["GET"])
def health_deep():
    """
    Deeper health check — also verifies the Chroma persistence path is
    accessible, reports which LLM provider is configured, and shows
    log file sizes so you can confirm file logging is working.
    """
    checks = {}
    status_code = 200
    
    # DB
    try:
        db.session.execute(db.text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        logger.error(f"Health check: database failed: {e}")
        checks["database"] = f"error: {e}"
        status_code = 503
        
    # Chroma path
    if os.path.isdir(CHROMA_DB_PATH) and os.access(CHROMA_DB_PATH, os.W_OK):
        checks["chroma_path"] = "ok"
    else:
        checks["chroma_path"] = f"error: '{CHROMA_DB_PATH}' missing or not writable"
        status_code = 503
        
    # SQLite file path
    sqlite_dir = os.path.dirname(SQLITE_DB_PATH)
    if os.path.isdir(sqlite_dir) and os.access(sqlite_dir, os.W_OK):
        checks["sqlite_dir"] = "ok"
    else:
        checks["sqlite_path"] = f"error: '{sqlite_dir}' missing or not writable"
        status_code = 503
        
    # LLM config presence (no actual API call — avoids burning quota)
    checks["llm_provider"] = LLM_PROVIDER
    checks["llm_model"] = LLM_MODEL
    
    # Log file status
    log_files = {}
    for name in ("app.log", "error.log", "access.log"):
        path = os.path.join(LOG_DIR, name)
        if os.path.exists(path):
            size_kb = round(os.path.getsize(path) / 1024, 1)
            log_files[name] = f"{size_kb} KB"
        else:
            log_files[name] = "not created yet (no log entries written)"
    checks["log_files"] = log_files
    
    return jsonify({
        "status": "ok" if status_code == 200 else "degraded",
        "checks": checks
    }), status_code