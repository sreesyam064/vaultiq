from extensions.db import db
from models._timestamps import utcnow

class User(db.Model):
    __tablename__ = "users"
     
    id = db.Column(
        db.Integer, 
        primary_key=True,
    )   #auto-incremeting IDs
    username = db.Column(
        db.String(100),
        unique=True,
        nullable=False,
        index=True,
    )
    email = db.Column(
        db.String(150),
        unique=True,
        nullable=False,
        index=True,
    )   # no duplicate emails
    password_hash = db.Column(
        db.String(255),
        nullable=False,
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=db.func.now()
    )
    
    def __repr__(self):
        return f"<User {self.username}>"
    
    documents = db.relationship(
        "Document",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )   # can do user.documents
    
    chat_sessions = db.relationship(
        "ChatSession",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )
    