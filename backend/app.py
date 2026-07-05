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

db.init_app(app)
jwt.init_app(app)
limiter.init_app(app)

app.register_blueprint(auth_bp)
app.register_blueprint(upload_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(health_bp)

logger.info(f"Routes registered: {[str(rule) for rule in app.url_map.iter_rules()]}")
# print(app.url_map)

@app.route("/")
def home():
    return {
        "message": "RAG API Running"
    }
    
             
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, use_reloader=False) # use_reloader=False to turn off automatic file-watching reloader.