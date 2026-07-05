from extensions.db import db
from datetime import datetime

class Document(db.Model):
    
    __tablename__ = "documents"
    
    id = db.Column(
        db.Integer,
        primary_key=True
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )
    filename = db.Column(
        db.String(255),
        nullable=False
    )
    filepath = db.Column(
        db.String(500),
        nullable=False
    )
    uploaded_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )
    
    # To make it readable
    def __repr__(self):
        return f"<Document {self.filename}>"