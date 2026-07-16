from extensions.db import db
from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)

class Document(db.Model):
    
    __tablename__ = "documents"

    # "already uploaded" duplicate check in upload_routes.py was pure application-logic (a SELECT before INSERT)
    # 2 concurrent requests for same user+ filename could both pass check before either commits, creating two Document rows
    # for same file. This constraint makes db itself final authority — second concurrent insert now fails atomically instead of silently succeding.
    __table_args__ = (   
        db.UniqueConstraint("user_id", "filename", name="uq_document_user_filename"),
    )
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
        default=_utcnow
    )
    
    # To make it readable
    def __repr__(self):
        return f"<Document {self.filename}>"