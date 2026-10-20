import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.auth import CurrentUser, get_current_user
from app.config import get_settings
from app.db import get_db
from app.ingestion import ACCEPTED_EXTENSIONS
from app.models import Document, DocumentStatus
from app.schemas import DocumentFileUrl, DocumentList, DocumentOut

log = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=DocumentList)
def list_documents(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    documents = db.scalars(
        select(Document).where(Document.owner_id == user.owner_id).order_by(Document.created_at.desc())
    ).all()
    return DocumentList(documents=[DocumentOut.model_validate(d) for d in documents])


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile | None = File(None),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stores the file and returns the document as `processing`. Indexing isn't
    started here: the object landing under S3_UPLOAD_PREFIX triggers an EventBridge
    event that queues it for the worker (`app/worker.py`)."""
    if file is None or not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No file provided")

    filename = Path(file.filename).name
    ext = Path(filename).suffix.lower()
    if ext not in ACCEPTED_EXTENSIONS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "File type not supported")

    # Starlette spools large uploads to a temporary file, so this doesn't load it into memory.
    size = file.file.seek(0, os.SEEK_END)
    file.file.seek(0)
    if size > get_settings().max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large")
    if size == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty")

    # The row is committed before the upload: the S3 event can reach the worker as
    # soon as the object exists, and the worker needs the row by then.
    document_id = uuid.uuid4()
    content_type = ACCEPTED_EXTENSIONS[ext]
    document = Document(
        id=document_id,
        owner_id=user.owner_id,
        filename=filename,
        content_type=content_type,
        size_bytes=size,
        storage_key=f"{get_settings().s3_upload_prefix}{user.owner_id}/{document_id}{ext}",
        status=DocumentStatus.PROCESSING,
    )
    db.add(document)
    db.commit()
    try:
        storage.save_file(document.storage_key, file.file, content_type)
    except Exception:
        db.delete(document)
        db.commit()
        raise
    db.refresh(document)
    return DocumentOut.model_validate(document)


@router.get("/{document_id}/file", response_model=DocumentFileUrl)
def document_file_url(
    document_id: str,
    download: bool = Query(False),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A short-lived presigned S3 URL for the original file. The browser fetches it
    straight from S3, so the bucket needs a CORS rule for the frontend origin."""
    document = _owned_document(db, user, document_id)
    expires_in = get_settings().file_url_expires_seconds
    url = storage.presigned_get_url(
        document.storage_key,
        document.content_type,
        _content_disposition("attachment" if download else "inline", document.filename),
        expires_in,
    )
    return DocumentFileUrl(
        url=url,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        filename=document.filename,
        content_type=document.content_type,
    )


def _content_disposition(kind: str, filename: str) -> str:
    # ASCII fallback plus RFC 5987 `filename*` so non-ASCII names survive.
    fallback = filename.encode("ascii", "replace").decode().replace('"', "'").replace("?", "_")
    return f'{kind}; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename)}'


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = _owned_document(db, user, document_id)
    storage_key = document.storage_key
    db.delete(document)  # chunks go with it via ON DELETE CASCADE
    db.commit()
    try:
        storage.delete(storage_key)
    except Exception:
        # The document is already gone for the user; an orphaned object is only a cleanup issue.
        log.exception("Couldn't delete stored file %s", storage_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _owned_document(db: Session, user: CurrentUser, document_id: str) -> Document:
    # 404 for malformed ids and other users' documents alike, so ids can't be probed.
    try:
        parsed = uuid.UUID(document_id)
    except ValueError:
        parsed = None
    document = db.get(Document, parsed) if parsed else None
    if document is None or document.owner_id != user.owner_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return document
