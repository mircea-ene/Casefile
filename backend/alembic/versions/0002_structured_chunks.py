"""structured chunks and full-text search

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column(
        "documents", sa.Column("parser_version", sa.Integer(), server_default="1", nullable=False)
    )

    op.alter_column("chunks", "page", new_column_name="page_start")
    op.add_column("chunks", sa.Column("page_end", sa.Integer(), nullable=True))
    op.execute("UPDATE chunks SET page_end = page_start")
    op.add_column("chunks", sa.Column("heading_path", sa.Text(), nullable=True))
    op.add_column("chunks", sa.Column("element_type", sa.Text(), server_default="text", nullable=False))
    op.add_column("chunks", sa.Column("source", sa.Text(), server_default="text_layer", nullable=False))
    op.add_column("chunks", sa.Column("bboxes", postgresql.JSONB(), nullable=True))
    op.add_column("chunks", sa.Column("embed_text", sa.Text(), nullable=True))
    op.execute("UPDATE chunks SET embed_text = content")
    op.alter_column("chunks", "embed_text", nullable=False)
    op.add_column("chunks", sa.Column("token_count", sa.Integer(), nullable=True))
    op.add_column(
        "chunks",
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=True,
        ),
    )
    op.create_index("ix_chunks_search_tsv", "chunks", ["search_tsv"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_chunks_search_tsv", table_name="chunks")
    for column in ("search_tsv", "token_count", "embed_text", "bboxes", "source", "element_type", "heading_path", "page_end"):
        op.drop_column("chunks", column)
    op.alter_column("chunks", "page_start", new_column_name="page")
    op.drop_column("documents", "parser_version")
    op.drop_column("documents", "page_count")
