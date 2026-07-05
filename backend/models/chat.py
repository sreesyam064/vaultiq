from extensions.db import db
from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)

class ChatSession(db.Model):
    
    __tablename__ = "chat_sessions"
    
    id = db.Column(
        db.Integer,
        primary_key=True
    )
    
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )
    
    title = db.Column(
        db.String(100),
        nullable=True
    )
    
    created_id = db.Column(
        db.DateTime,
        default=_utcnow
    )
    
    messages = db.relationship(
        "Message",
        backref="session",
        lazy=True
    )
    
    
class Message(db.Model):
    
    __tablename__ = "messages"
    
    id = db.Column(
        db.Integer,
        primary_key=True
    )
    
    session_id = db.Column(
        db.Integer,
        db.ForeignKey("chat_sessions.id"),
        nullable=False
    )
    
    role = db.Column(
        db.String(20),
        nullable=False        
    )
    
    content = db.Column(
        db.Text,
        nullable=False
    )
    
    timestamp = db.Column(
        db.DateTime,
        default=_utcnow
    )
    