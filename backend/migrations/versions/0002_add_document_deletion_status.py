"""
add deletion_status to documents

Revision ID: 0002
Revisis: 0001
Create Date: 2026-07-21

Adds deletion_status to safely track document deletion across Postgres,
ChromaDB, and R2/local storage.

Documents are marked "deleting" before cleanup begins, hiding them from
active listings and allowing partially failed deletions to be retried.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "documents",
        sa.Column(
            "deletion_status", sa.String(length=20),
            nullable=False, server_default="active",
        ),
    )
    
    
def downgrade():
    op.drop_column("documents", "deletion_status")
    