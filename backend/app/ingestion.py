"""Indexing, run by the queue worker (`app/worker.py`): parse (app.parsing), chunk
(app.chunking), embed, store."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import PurePath

from sqlalchemy import delete, select, update

from app import ai, storage, tracing
from app.chunking import build_sections, chunk_document
from app.db import SessionLocal
from app.models import Chunk, Document, DocumentStatus, Section
from app.parsing import ExtractionError, parse

log = logging.getLogger(__name__)

# Bump when parsing or chunking changes in a way that warrants re-indexing
# (`python -m app.reindex` picks up documents with an older version).
PARSER_VERSION = 4

# Extensions the upload endpoint accepts (matches the frontend's file picker).
ACCEPTED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".rtf": "application/rtf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


class IndexResult:
    INDEXED = "indexed"
    FAILED = "failed"  # unsupported content: retrying won't help
    GAVE_UP = "gave_up"  # failed on the last attempt (marked failed); the queue should dead-letter it
    SKIPPED = "skipped"  # nothing to do: deleted, already finished, or not our object


def index_document(
    document_id: uuid.UUID, *, storage_key: str | None = None, final_attempt: bool = True
) -> str:
    """Indexes one `processing` document; returns an IndexResult.

    Safe to run more than once for the same document (queue redelivery, two
    workers): anything not `processing` is skipped, and the write locks the
    document row and re-checks, so only one run's chunks are stored.

    Unsupported content fails the document right away. Other errors (model
    server or database down, ...) are raised so the job is retried, unless
    `final_attempt`, which marks the document failed instead."""
    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if document is None:
            log.info("Document %s no longer exists; nothing to index", document_id)
            return IndexResult.SKIPPED
        if storage_key is not None and document.storage_key != storage_key:
            log.warning("Object %s doesn't belong to document %s; ignored", storage_key, document_id)
            return IndexResult.SKIPPED
        if document.status != DocumentStatus.PROCESSING:
            log.info("Document %s is already %s; nothing to do", document_id, document.status)
            return IndexResult.SKIPPED
        owner_id, filename, key = document.owner_id, document.filename, document.storage_key
    # Parsing and embedding take minutes on large documents, so no transaction
    # (or pooled connection) is held while they run.

    try:
        with tracing.trace(
            "index_document",
            user_id=owner_id,
            input=filename,
            metadata={"document_id": str(document_id), "parser_version": str(PARSER_VERSION)},
        ) as root:
            ext = PurePath(key).suffix.lower()
            with tracing.span("parse"):
                parsed = parse(storage.load(key), ext)
            title = PurePath(filename).stem
            drafts = chunk_document(parsed.elements, title=title)
            section_drafts = build_sections(drafts, title=title)
            embeddings = ai.embed_documents([d.embed_text for d in drafts] + [s.embed_text for s in section_drafts])
            root.update(output={"pages": parsed.page_count, "chunks": len(drafts), "sections": len(section_drafts)})
        if not _store(document_id, parsed, drafts, section_drafts, embeddings):
            return IndexResult.SKIPPED
    except ExtractionError as exc:
        log.warning("Can't index document %s: %s", document_id, exc)
        mark_failed(document_id, str(exc))
        return IndexResult.FAILED
    except Exception as exc:
        if not final_attempt:
            log.warning("Indexing document %s failed; will retry: %s", document_id, exc)
            raise
        log.exception("Indexing failed for document %s on its last attempt", document_id)
        mark_failed(document_id, str(exc))
        return IndexResult.GAVE_UP
    log.info("Indexed document %s into %d chunks in %d sections", document_id, len(drafts), len(section_drafts))
    return IndexResult.INDEXED


def _store(document_id: uuid.UUID, parsed, drafts, section_drafts, embeddings) -> bool:
    """Replaces the document's chunks and sections and marks it ready, in one
    commit. False if, by now, it was deleted or another run finished it."""
    chunk_embeddings, section_embeddings = embeddings[: len(drafts)], embeddings[len(drafts) :]
    with SessionLocal() as db:
        document = db.scalars(select(Document).where(Document.id == document_id).with_for_update()).first()
        if document is None or document.status != DocumentStatus.PROCESSING:
            return False
        db.execute(delete(Chunk).where(Chunk.document_id == document.id))
        db.execute(delete(Section).where(Section.document_id == document.id))
        sections = [
            Section(
                id=uuid.uuid4(),
                document_id=document.id,
                owner_id=document.owner_id,
                section_index=i,
                heading_path=draft.heading_path,
                token_count=draft.token_count,
                embed_text=draft.embed_text,
                embedding=embedding,
            )
            for i, (draft, embedding) in enumerate(zip(section_drafts, section_embeddings, strict=True))
        ]
        section_of = {i: s.id for s, d in zip(sections, section_drafts) for i in d.chunk_indexes}
        db.add_all(sections)
        db.flush()  # sections before the chunks that reference them
        db.add_all(
            Chunk(
                document_id=document.id,
                section_id=section_of[i],
                owner_id=document.owner_id,
                chunk_index=i,
                page_start=draft.page_start,
                page_end=draft.page_end,
                heading_path=draft.heading_path,
                section=draft.section,
                element_type=draft.element_type,
                source=draft.source,
                bboxes=draft.bboxes or None,
                content=draft.content,
                embed_text=draft.embed_text,
                token_count=draft.token_count,
                embedding=embedding,
            )
            for i, (draft, embedding) in enumerate(zip(drafts, chunk_embeddings, strict=True))
        )
        document.page_count = parsed.page_count
        document.parser_version = PARSER_VERSION
        document.status = DocumentStatus.READY
        document.error = None
        db.commit()
    return True


def mark_failed(document_id: uuid.UUID, error: str) -> None:
    """Fails a document that is still processing (not one another run finished)."""
    with SessionLocal() as db:
        db.execute(
            update(Document)
            .where(Document.id == document_id, Document.status == DocumentStatus.PROCESSING)
            .values(status=DocumentStatus.FAILED, error=error[:1000])
        )
        db.commit()



def fail_stale_indexing(older_than_seconds: int) -> int:
    """Fails documents stuck in processing: their message went to the dead-letter
    queue, or the worker died on the last attempt. `updated_at` is when they were
    set to processing (upload or re-index); indexing doesn't touch the row before
    it finishes. Returns how many were failed."""
    cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
    with SessionLocal() as db:
        result = db.execute(
            update(Document)
            .where(Document.status == DocumentStatus.PROCESSING, Document.updated_at < cutoff)
            .values(status=DocumentStatus.FAILED, error="Indexing didn't finish (gave up after retries)")
        )
        db.commit()
    return result.rowcount
