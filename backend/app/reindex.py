"""Re-index documents after the ingestion pipeline changes.

    python -m app.reindex            # documents indexed by an older PARSER_VERSION, plus failed ones
    python -m app.reindex --all      # every document

Sets them to processing and queues them for the worker (`python -m app.worker`),
which must be running. Documents show as processing until it gets to them."""

import argparse
import logging

from sqlalchemy import or_, select

from app import indexing_queue
from app.db import SessionLocal
from app.ingestion import PARSER_VERSION
from app.models import Document, DocumentStatus


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="re-index every document")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    with SessionLocal() as db:
        query = select(Document).order_by(Document.created_at)
        if not args.all:
            query = query.where(
                or_(Document.parser_version < PARSER_VERSION, Document.status == DocumentStatus.FAILED)
            )
        documents = db.scalars(query).all()
        for document in documents:
            document.status = DocumentStatus.PROCESSING
        # Committed before queueing, since the worker only indexes processing documents.
        # If queueing fails part-way, the rest stay processing until the worker's stale
        # sweep fails them; run this again then.
        db.commit()
        ids = [d.id for d in documents]

    for document_id in ids:
        indexing_queue.send(document_id)
    logging.info("Queued %d document(s) for re-indexing", len(ids))


if __name__ == "__main__":
    main()
