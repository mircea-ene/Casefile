"""Run retrieval only (embedding + hybrid search, no LLM) and print the chunks.

    python -m app.search "What is under clause 2.6 in Purpose and Agreement?"
    python -m app.search "..." --document "Lease Agreement.pdf" --all --full

Prints the query analysis (search query, contracts named and the documents they
resolved to, BM25 terms), then three lists:
- chunk hits: ✓ = in the top-k above the similarity floor (these pick sections),
  with cosine similarity, rank in vector and full-text search (— = not a
  candidate there) and fused RRF score;
- the sections they picked, with score, the section embedding's similarity,
  whether the whole section was sent and why (else only its hit chunks), and how
  many of its chunks went in;
- what the LLM would get, in prompt order (+ = included because of its section).
Needs LM Studio running with the embedding model, and the LLM for query analysis
(--no-analysis skips it); the answer isn't generated."""

import argparse
import textwrap

from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Document
from app.rag import retrieve_context


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    parser.add_argument("--owner", help="owner id (Cognito sub); defaults to the only owner in the database")
    parser.add_argument("--document", action="append", help="limit to a document filename (repeatable)")
    parser.add_argument("--all", action="store_true", help="show every chunk candidate, not just the top-k hits")
    parser.add_argument("--full", action="store_true", help="print whole chunks instead of a preview")
    parser.add_argument("--no-analysis", action="store_true", help="search the question as typed (no LLM call)")
    args = parser.parse_args()
    settings = get_settings()
    settings.query_analysis = settings.query_analysis and not args.no_analysis

    with SessionLocal() as db:
        owner = args.owner
        if owner is None:
            owners = db.scalars(select(Document.owner_id).distinct()).all()
            if len(owners) != 1:
                parser.error(f"{len(owners)} owners in the database; pass --owner (one of: {', '.join(owners)})")
            owner = owners[0]

        document_ids = None
        if args.document:
            documents = db.execute(
                select(Document.id, Document.filename).where(
                    Document.owner_id == owner, Document.filename.in_(args.document)
                )
            ).all()
            missing = set(args.document) - {d.filename for d in documents}
            if missing:
                parser.error(f"no such document for this owner: {', '.join(sorted(missing))}")
            document_ids = [d.id for d in documents]

        total = db.scalar(select(func.count()).select_from(Document).where(Document.owner_id == owner))
        retrieval = retrieve_context(db, owner, args.question, document_ids)
        names = dict(
            db.execute(select(Document.id, Document.filename).where(Document.id.in_(retrieval.document_ids or []))).all()
        )

    analysis = retrieval.analysis
    if analysis is not None:
        print(f"Search query: {analysis.search_query}" + ("" if analysis.analyzed else "  (not analyzed)"))
        if analysis.contracts:
            scoped = ", ".join(names.get(i, str(i)) for i in retrieval.document_ids or []) or "all documents"
            print(f"Contracts named: {analysis.contracts} -> searching {scoped}")
        print(f"BM25: {analysis.bm25_query or 'skipped (no clause numbers or exact terms)'}\n")

    hits, seeds = retrieval.hits, retrieval.seeds
    seed_ids = {id(h) for h in seeds}
    print(
        f"{len(hits)} chunk candidates from {total} documents; {len(seeds)} hits pick sections "
        f"(top {settings.retrieval_top_k}, similarity >= {settings.retrieval_min_similarity})\n"
    )
    shown = hits if args.all else seeds
    for n, hit in enumerate(shown, start=1):
        mark = "✓" if id(hit) in seed_ids else " "
        ranks = f"vector #{hit.vector_rank or '—'}  text #{hit.text_rank or '—'}"
        print(f"{mark} {n:>2}. sim {hit.source.similarity:.3f}  {ranks}  rrf {hit.rrf_score:.4f}")
        _print_chunk(hit.source, args.full)

    print(f"Sections, best first (budget {settings.retrieval_token_budget} tokens; section sim = its own embedding):\n")
    for pick in retrieval.sections:
        similarity = f"section sim {pick.similarity:.3f}" if pick.similarity is not None else "section sim —"
        whole = f"whole ({pick.expanded})" if pick.expanded else "hits only"
        print(
            f"  score {pick.score:.4f}  {similarity}  {whole:<24}  sent {pick.chunks_sent}/{pick.chunk_count} chunks  "
            f"{pick.document_name}  |  {pick.heading_path or '(no section)'}"
        )

    tokens = sum(s.token_count for s in retrieval.sources)
    print(f"\nSent to the LLM, in prompt order ({len(retrieval.sources)} chunks, {tokens} tokens; + = added by section):\n")
    for n, source in enumerate(retrieval.sources, start=1):
        mark = "+" if source.match == "section" else "✓"
        print(f"{mark} [{n}] sim {source.similarity:.3f}  {source.token_count} tokens")
        _print_chunk(source, args.full)


def _print_chunk(source, full: bool) -> None:
    location = ", ".join(filter(None, [source.document_name, f"p{source.page}" if source.page else None]))
    print(f"     {location}  |  {source.heading_path or source.section or '(no section)'}")
    body = source.content if full else textwrap.fill(textwrap.shorten(source.content, 300, placeholder=" …"), 110)
    print(textwrap.indent(body, "     "))
    print()


if __name__ == "__main__":
    main()
