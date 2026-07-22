import os
import time
import uuid
import logging

from flask import Flask, jsonify, g, request
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request

from logging_config import setup_logging
setup_logging()

from config import ( 
    SECRET_KEY,
    JWT_SECRET_KEY,
    SQLALCHEMY_DATABASE_URI,
    SQLALCHEMY_TRACK_MODIFICATIONS,
    SQLALCHEMY_ENGINE_OPTIONS,
    UPLOAD_FOLDER,
    MAX_UPLOAD_SIZE_BYTES,
    validate_config,
)

# fail fast on bad config instead of crashing deep inside a request
validate_config()   

from extensions import db, jwt, limiter, migrate

from routes import auth_bp, chat_bp, upload_bp, health_bp

logger = logging.getLogger(__name__)

app = Flask(__name__)

app.config["SECRET_KEY"] = SECRET_KEY
app.config["JWT_SECRET_KEY"] = JWT_SECRET_KEY
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = SQLALCHEMY_TRACK_MODIFICATIONS
# To limit server-side size to eliminate taking down disk/memory by large request body before app code even run
# MAX_CONTENT_LENGTH enforced by werkzeug at WSGI layer, before flask parses request body at all.
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_SIZE_BYTES
# pool_pre_ping, pool_recycle for Postgres (Neon), no-op on SQLite.
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = SQLALCHEMY_ENGINE_OPTIONS

db.init_app(app)
jwt.init_app(app)
limiter.init_app(app)
migrate.init_app(app, db)

app.register_blueprint(auth_bp)
app.register_blueprint(upload_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(health_bp)

logger.info(f"Routes registered: {[str(rule) for rule in app.url_map.iter_rules()]}")

access_logger = logging.getLogger("http.access")

@app.before_request
def _start_request_context():
    """
    Runs before each request.

    Generates a request ID for log correlation, records the request
    start time, and extracts the user ID from a valid JWT (if present).
    Public routes continue normally when no token is provided.
    
    """
    g.request_id = str(uuid.uuid4())[:8]
    g.request_start_time = time.time()
    g.user_id = None

    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity is not None:
            g.user_id = identity
    except Exception:
        # Invalid/expired token on request that doesn't strictly require auth — leave
        # user_id as None, let route's own @jwt_required() (if any) handle rejecting request properly.
        pass


@app.after_request
def _log_request_completion(response):
    """
    Runs after every request.
    Logs request metadata (endpoint, method, status, latency) and adds the request ID to the response for log tracing.
    Also stamps X-Request-ID on response itself, so specific response can be matched back to its exact log line.
    """
    start = getattr(g, "request_start_time", None)
    processing_time_ms = round((time.time() - start) * 1000, 2) if start else None

    access_logger.info(
        "request completed",
        extra={
            "endpoint": request.path,
            "method": request.method,
            "status": response.status_code,
            "processing_time_ms": processing_time_ms,
            "remote_addr": request.remote_addr,
        },
    )

    response.headers["X-Request-ID"] = getattr(g, "request_id", "")
    return response

@app.route("/")
def home():
    return {
        "message": "RAG API Running"
    }
    
@app.errorhandler(413)
def request_entity_too_large(e):
    # Without this handler, exceeding MAX_CONTENT_LENGTH returns flask's default
    # HTML error page instead of JSON — breaking frontend, which always expects a JSON body from this API.
    from config import MAX_UPLOAD_SIZE_MB
    return jsonify({
        "error": f"Upload too large. Maximum total size is {MAX_UPLOAD_SIZE_MB}MB.",
    }), 413   

@app.errorhandler(404)
def not_found(e):
    # Flask's default 404 ia a HTML page. This ia a JSON-only API — including errors, should be JSON so
    # forntend never has to special-case and HTML body.
    return jsonify({"error": "The requested endpoint does not exist."}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    # Same reasoning as 404 handler — JSON, not Flask's default HTML.
    return jsonify({"error": "This HTTP method is not allowed on this endpoint."}), 405

@app.errorhandler(Exception)
def handle_exception(e):
    """
    Catch any unhandled exception and return a consistent JSON response.
    HTTP exceptions keep their original status codes, while unexpected
    errors are logged with a traceback and returned as a generic 500.
    """
    from werkzeug.exceptions import HTTPException
    
    if isinstance(e, HTTPException):
        # Preserve original HTTP status code and message instead of forcing everything to 500
        return jsonify({"error": e.description or "Request error."}), e.code
    
    logger.error(f"Unhandled exception on {request.method} {request.path}: {e}", exc_info=True)
    return jsonify({"error": "An unexpected error occurred. Please try again in a moment."}), 500


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)