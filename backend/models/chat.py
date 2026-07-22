from extensions.db import db
from models._timestamps import utcnow

class ChatSession(db.Model):
    
    __tablename__ = "chat_sessions"
    
    id = db.Column(
        db.Integer,
        primary_key=True
    )
    
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    title = db.Column(
        db.String(100),
        nullable=True
    )
    
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=db.func.now(),
    )
    
    messages = db.relationship(
        "Message",
        backref="session",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="Message.timestamp",
    )
    
    
class Message(db.Model):
    
    __tablename__ = "messages"
    
    id = db.Column(
        db.Integer,
        primary_key=True
    )
    
    session_id = db.Column(
        db.Integer,
        db.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=db.func.now(),
    )
    