"""sections: top-level document sections with their own embedding

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("section_index", sa.Integer(), nullable=False),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embed_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sections_document", "sections", ["document_id"])
    op.create_index("ix_sections_owner", "sections", ["owner_id"])
    op.create_index(
        "ix_sections_embedding",
        "sections",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.add_column(
        "chunks",
        sa.Column("section_id", sa.Uuid(), sa.ForeignKey("sections.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_chunks_section", "chunks", ["section_id"])


def downgrade() -> None:
    op.drop_index("ix_chunks_section", table_name="chunks")
    op.drop_column("chunks", "section_id")
    op.drop_table("sections")
