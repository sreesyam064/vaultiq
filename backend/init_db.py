import logging

from app import app
from extensions import db

logger = logging.getLogger(__name__)

with app.app_context():
        db.create_all()
        logger.info("Database initialized successfully.")
        
    