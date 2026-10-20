"""index section paths in search_tsv for BM25

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# Copied rather than imported so the migration doesn't change if the model does.
NEW_EXPRESSION = (
    "setweight(to_tsvector('english', coalesce(heading_path, '')), 'A') || "
    "setweight(to_tsvector('english', content), 'B')"
)
OLD_EXPRESSION = "to_tsvector('english', content)"


def _replace_search_tsv(expression: str) -> None:
    # A generated column's expression can't be altered in place; recomputing it
    # rewrites the table but needs no re-embedding.
    op.drop_index("ix_chunks_search_tsv", table_name="chunks")
    op.drop_column("chunks", "search_tsv")
    op.add_column(
        "chunks",
        sa.Column("search_tsv", postgresql.TSVECTOR(), sa.Computed(expression, persisted=True), nullable=True),
    )
    op.create_index("ix_chunks_search_tsv", "chunks", ["search_tsv"], postgresql_using="gin")


def upgrade() -> None:
    _replace_search_tsv(NEW_EXPRESSION)


def downgrade() -> None:
    _replace_search_tsv(OLD_EXPRESSION)
