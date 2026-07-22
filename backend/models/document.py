from extensions.db import db
from models._timestamps import utcnow

class Document(db.Model):
    """
    filepath stores a *storage object key* (e.g. "users/3/17/report.pdf" on R2,
    or a relative path under UPLOAD_FOLDER locally) — not an absolute local file system path.
    
    filepath is nullable during brief window between "row created to obtain document.id" and
    "storage upload succeeded" in upload flow — a row with filepath=None means ingestion never
    completed and should be treated as not-yetr-uploaded by any code that reads this table directly.
    
    deletion_status makes deletion across Postgres, ChromaDB, and R2 safe.
    "active" means the document is available normally.
    "deleting" means cleanup is in progress or partially failed. 
    The document is hidden from active listings and deletion can be retried.
    The database row is removed only after all cleanup succeeds.
    """
    __tablename__ = "documents"
       
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
    filename = db.Column(
        db.String(255),
        nullable=False
    )
    filepath = db.Column(
        db.String(500),
        nullable=True
    )
    status = db.Column(
        db.String(20),
        nullable=False,
        default="processing",
        server_default="processing",
        index=True,
    )
    uploaded_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=db.func.now(),
    )
    deletion_status = db.Column(
        db.String(20),
        nullable=False,
        default="active",
        server_default="active",
    )
    
    # "already uploaded" duplicate check in upload_routes.py was pure application-logic (a SELECT before INSERT)
    # 2 concurrent requests for same user+ filename could both pass check before either commits, creating two Document rows
    # for same file. This constraint makes db itself final authority — second concurrent insert now fails atomically instead of silently succeding.
    __table_args__ = (   
        db.UniqueConstraint("user_id", "filename", name="uq_document_user_filename"),
    )
    
    def __repr__(self):
        return f"<Document {self.filename}>"