import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import get_settings


SEARCH_TSV_EXPRESSION = (
    "setweight(to_tsvector('english', coalesce(heading_path, '')), 'A') || "
    "setweight(to_tsvector('english', content), 'B')"
)


class Base(DeclarativeBase):
    pass


class DocumentStatus:
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("status IN ('processing', 'ready', 'failed')", name="documents_status_check"),
        Index("ix_documents_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Cognito `sub` for now; becomes the tenant id once tenancy lands.
    owner_id: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default=DocumentStatus.PROCESSING)
    # Internal reason for a failed status; not exposed by the API.
    error: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    # Which ingestion pipeline produced the chunks (app.ingestion.PARSER_VERSION),
    # so documents can be re-indexed when it changes.
    parser_version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", passive_deletes=True)


class Section(Base):
    """A top-level section of a document (a numbered clause like "2. Obligations",
    an exhibit, or the preamble), made of consecutive chunks. Embedded on its own
    so retrieval can match a whole section; see app.rag.retrieve."""

    __tablename__ = "sections"
    __table_args__ = (
        Index("ix_sections_document", "document_id"),
        Index("ix_sections_owner", "owner_id"),
        Index(
            "ix_sections_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    owner_id: Mapped[str] = mapped_column(Text)
    section_index: Mapped[int] = mapped_column(Integer)
    # Breadcrumb down to the section, e.g. "SERVICES AND HOSTING AGREEMENT > 2. VOTOCAST'S OBLIGATIONS".
    heading_path: Mapped[str | None] = mapped_column(Text)
    # Sum of its chunks' token counts (the whole section, not just what was embedded).
    token_count: Mapped[int] = mapped_column(Integer)
    # Breadcrumb + the section's text, cut at SECTION_EMBED_MAX_TOKENS.
    embed_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(get_settings().embedding_dimensions))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_document", "document_id"),
        Index("ix_chunks_section", "section_id"),
        Index("ix_chunks_owner", "owner_id"),
        Index("ix_chunks_search_tsv", "search_tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    # NULL only for chunks indexed before parser_version 4.
    section_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sections.id", ondelete="SET NULL"))
    # Denormalized from documents so retrieval filters without a join (and RLS later).
    owner_id: Mapped[str] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    # Breadcrumb like "5. TERM AND TERMINATION > 5.2 Termination for Cause".
    heading_path: Mapped[str | None] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(Text)
    element_type: Mapped[str] = mapped_column(Text, server_default="text")  # text | table | definition
    source: Mapped[str] = mapped_column(Text, server_default="text_layer")  # text_layer | ocr
    # [{"page", "x", "y", "width", "height"}], fractions of the page, top-left origin
    # (parser_version >= 3; older chunks hold {"page", "l", "t", "r", "b"} in PDF points).
    bboxes: Mapped[list[dict] | None] = mapped_column(JSONB)
    # Literal document text: what citations quote and the LLM sees.
    content: Mapped[str] = mapped_column(Text)
    # Breadcrumb + content: only what was embedded.
    embed_text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(Vector(get_settings().embedding_dimensions))
    # Section path (weight A) + body (weight B); BM25 in app.rag boosts weight-A hits.
    search_tsv: Mapped[str] = mapped_column(TSVECTOR, Computed(SEARCH_TSV_EXPRESSION, persisted=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_owner_updated", "owner_id", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str] = mapped_column(Text)
    # Written by the LLM after the first turn (app.conversations.generate_title).
    # NULL while that is still running.
    generated_title: Mapped[str | None] = mapped_column(Text)
    # Set by the user; takes precedence over the generated title.
    custom_title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Bumped on every new turn so the list can show the most recent conversations first.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    turns: Mapped[list["Turn"]] = relationship(
        back_populates="conversation", passive_deletes=True, order_by="Turn.created_at"
    )


class Turn(Base):
    """One question and the answer to it. Citations and sources are a snapshot of
    what the user saw, so history survives re-indexing (which replaces chunks)."""

    __tablename__ = "turns"
    __table_args__ = (Index("ix_turns_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    owner_id: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    # The chat's document filter; NULL means all of the owner's documents.
    document_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)))
    answer: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict]] = mapped_column(JSONB)
    sources: Mapped[list[dict]] = mapped_column(JSONB)
    insufficient_evidence: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="turns")
