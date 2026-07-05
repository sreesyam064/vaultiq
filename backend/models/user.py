from extensions.db import db

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
    )
    email = db.Column(
        db.String(150),
        unique=True,
        nullable=False,
    )   # no duplicate emails
    password_hash = db.Column(
        db.String(255),
        nullable=False,
    )
    
    def __repr__(self):
        return f"<User {self.username}>"
    
    documents = db.relationship(
        "Document",
        backref="user",
        lazy=True
    )   # can do user.documents
    
    chat_sessions = db.relationship(
        "ChatSession",
        backref="user",
        lazy=True
    )
    