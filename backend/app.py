import os
import logging

from flask import Flask, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from logging_config import setup_logging
setup_logging() # must run before any other module-level logger.info() calls

from config import ( 
    SECRET_KEY,
    JWT_SECRET_KEY,
    SQLALCHEMY_DATABASE_URI,
    SQLALCHEMY_TRACK_MODIFICATIONS,
    UPLOAD_FOLDER,
    MAX_UPLOAD_SIZE_BYTES,
    validate_config,
)

# fail fast on bad config instead of crashing deep inside a request
validate_config()   

from extensions import db, jwt, limiter

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

db.init_app(app)
jwt.init_app(app)
limiter.init_app(app)

app.register_blueprint(auth_bp)
app.register_blueprint(upload_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(health_bp)

logger.info(f"Routes registered: {[str(rule) for rule in app.url_map.iter_rules()]}")

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
    
if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)