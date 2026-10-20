"""Question answering: hybrid retrieval, a cited answer from the LLM, quote verification."""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import Text, bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Session

from app import ai, tracing
from app.config import get_settings
from app.models import Chunk, Document, Section
from app import schemas
from app.schemas import ChatAnswer, Citation

SYSTEM_PROMPT = """You answer questions about a law firm's documents using ONLY the numbered sources provided.

Rules:
- Every factual statement in "answer" must end with a citation marker like [2] naming the source it comes from. Use only source numbers that exist.
- For every source you cite, add an entry to "citations" with that source number and a short quote copied character-for-character from that source's text that supports the statement. Do not paraphrase quotes.
- If the sources don't clearly answer the question, set "insufficient_evidence" to true, leave "answer" empty and "citations" empty. Never guess or use outside knowledge.
- Be concise and precise; this is for lawyers.

Format of "answer":
- Start with one sentence that answers the question directly.
- When the answer has several items (obligations, rights, conditions, deadlines, amounts), list them with "- " bullets, one item per line, each one or two sentences ending with its citation marker. Summarize each clause in plain words; don't copy it out in full (the quotes do that).
- Begin a list item with the clause in bold when the source names one, like "**2.1 Privacy:** ...".
- Keep categories apart: obligations (what a party must or must not do) are not warranties, representations or liability limits. If the question asks for one, don't list the others as if they were it.
- Separate paragraphs with a blank line. Only use paragraphs, "- " or "1. " lists (sub-items indented by two spaces) and **bold**: no headings, tables, links or HTML."""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "insufficient_evidence": {"type": "boolean"},
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"source": {"type": "integer"}, "quote": {"type": "string"}},
                "required": ["source", "quote"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["insufficient_evidence", "answer", "citations"],
    "additionalProperties": False,
}

_MARKER_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")

# Reciprocal rank fusion constant (the usual default from the RRF paper).
RRF_K = 60

# Hierarchical retrieval sends a section whole only when it is clearly what the
# question is about (see _expand_reason); otherwise just its hit chunks.
SECTION_MIN_HITS = 2
# Share of a section heading's words (English lexemes, numbers excluded) that must
# appear in the question: "Votocast's obligations" vs "2. VOTOCAST'S OBLIGATIONS".
SECTION_HEADING_OVERLAP = 0.5
# The best section-embedding match also expands when it leads the runner-up by this
# much cosine similarity (untuned).
SECTION_EMBEDDING_LEAD = 0.03

_LEXEMES_SQL = text(
    "SELECT tsvector_to_array(to_tsvector('english', t)) FROM unnest(:texts) WITH ORDINALITY AS x(t, i) ORDER BY i"
).bindparams(bindparam("texts", type_=ARRAY(Text)))
_SECTION_NUMBER_RE = re.compile(r"^\s*(?:(?:section|article|clause)\s+|§\s*)?(\d+|[IVXLC]+)\b\.?", re.IGNORECASE)

# Okapi BM25 parameters (standard defaults): term-frequency saturation and
# document-length normalization.
BM25_K1 = 1.2
BM25_B = 0.75
# A term found in a chunk's section path (weight A in search_tsv) counts this
# many times an occurrence in the body.
BM25_HEADING_BOOST = 2.0

# Postgres' ts_rank has no IDF, so "agreement" (in every chunk) weighs as much as
# "2.6" (in one). This computes BM25 instead, from the chunks in scope:
#   idf(t)   = ln(1 + (N - df + 0.5) / (df + 0.5))
#   score(c) = sum over query terms of idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))
# tf counts positions in the tsvector (heading positions boosted); dl is the
# chunk's token_count. Each step uses the GIN index on search_tsv.
_BM25_SQL = text(
    """
WITH terms AS (
    SELECT DISTINCT lexeme, quote_literal(lexeme)::tsquery AS query
    FROM unnest(tsvector_to_array(to_tsvector('english', :question))) AS lexeme
),
scope_stats AS (
    SELECT count(*) AS n, coalesce(avg(coalesce(token_count, 1)), 1) AS avgdl
    FROM chunks
    WHERE owner_id = :owner_id AND (:document_ids IS NULL OR document_id = ANY(:document_ids))
),
idf AS (
    SELECT t.lexeme, ln(1 + (s.n - d.df + 0.5) / (d.df + 0.5)) AS idf
    FROM terms t
    CROSS JOIN scope_stats s
    CROSS JOIN LATERAL (
        SELECT count(*) AS df FROM chunks c
        WHERE c.owner_id = :owner_id
          AND (:document_ids IS NULL OR c.document_id = ANY(:document_ids))
          AND c.search_tsv @@ t.query
    ) d
    WHERE d.df > 0
),
matches AS (
    SELECT c.id, coalesce(c.token_count, 1) AS dl, c.search_tsv
    FROM chunks c
    WHERE c.owner_id = :owner_id
      AND (:document_ids IS NULL OR c.document_id = ANY(:document_ids))
      AND c.search_tsv @@ (SELECT string_agg(quote_literal(lexeme), ' | ')::tsquery FROM idf)
)
SELECT m.id
FROM matches m
CROSS JOIN scope_stats s
CROSS JOIN LATERAL unnest(m.search_tsv) AS term(lexeme, positions, weights)
JOIN idf ON idf.lexeme = term.lexeme
CROSS JOIN LATERAL (
    SELECT sum(CASE WHEN w = 'A' THEN :heading_boost ELSE 1 END) AS tf FROM unnest(term.weights) AS w
) f
GROUP BY m.id
ORDER BY sum(idf.idf * f.tf * (:k1 + 1) / (f.tf + :k1 * (1 - :b + :b * m.dl / s.avgdl))) DESC
LIMIT :limit
"""
).bindparams(bindparam("document_ids", type_=ARRAY(UUID(as_uuid=True))))

class DocumentNotFound(Exception):
    pass


@dataclass
class Source:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    page: int | None
    section: str | None
    heading_path: str | None
    content: str
    page_end: int | None = None
    element_type: str = "text"
    text_source: str = "text_layer"
    bboxes: list[dict] | None = None
    similarity: float = 0.0
    section_id: uuid.UUID | None = None
    chunk_index: int = 0
    token_count: int = 0
    # "hit": found by search itself; "section": sent because its section was.
    match: str = "hit"


def insufficient(sources: list[Source] = ()) -> ChatAnswer:
    """The sources are still returned, so the UI can show what was searched."""
    return ChatAnswer(
        answer="", citations=[], sources=[_source_out(s, None) for s in sources], insufficient_evidence=True
    )


def parse_document_ids(raw_document_ids: list[str] | None) -> list[uuid.UUID] | None:
    if raw_document_ids is None:
        return None
    try:
        return [uuid.UUID(i) for i in raw_document_ids]
    except ValueError:
        raise DocumentNotFound


def answer_question(db: Session, owner_id: str, question: str, document_ids: list[uuid.UUID] | None) -> ChatAnswer:
    if document_ids is not None:
        wanted = set(document_ids)
        owned = set(
            db.scalars(select(Document.id).where(Document.owner_id == owner_id, Document.id.in_(wanted)))
        )
        if owned != wanted:
            raise DocumentNotFound
        if not wanted:
            return insufficient()

    with tracing.span("retrieve", as_type="retriever", input=question) as span:
        sources = retrieve(db, owner_id, question, document_ids)
        span.update(output=[_trace_source(s) for s in sources])
    if not sources:
        result = insufficient()
    else:
        raw = ai.complete_json(SYSTEM_PROMPT, _user_prompt(question, sources), ANSWER_SCHEMA, name="answer")
        result = build_answer(raw, sources)
    _score_answer(result, sources)
    return result


def _trace_source(source: Source) -> dict:
    return {
        "document": source.document_name,
        "section": source.heading_path,
        "match": source.match,
        "similarity": round(source.similarity, 3),
        "tokens": source.token_count,
    }


def _score_answer(result: ChatAnswer, sources: list[Source]) -> None:
    """Per-request metrics for Langfuse; token usage itself comes from the model calls."""
    cited = sum(1 for s in result.sources if s.citation is not None)
    tracing.score("insufficient_evidence", result.insufficient_evidence)
    tracing.score("sources_sent", len(sources))
    tracing.score("context_tokens", sum(s.token_count for s in sources))
    tracing.score("citations", len(result.citations))
    # Share of the sent context that the answer actually cites: low means tokens
    # spent on sources that didn't help.
    if sources:
        tracing.score("cited_share", round(cited / len(sources), 3))


@dataclass
class Hit:
    source: Source  # source.similarity is the cosine similarity
    vector_rank: int | None
    text_rank: int | None
    rrf_score: float


@dataclass
class SectionPick:
    """A section considered for the prompt, for `python -m app.search`."""

    heading_path: str | None
    document_name: str
    score: float
    similarity: float | None  # of the section's own embedding, when it matched
    chunk_count: int
    chunks_sent: int
    # Why the whole section was sent ("2 hits", "heading", "section number",
    # "section embedding"), or None when only its hit chunks were.
    expanded: str | None


@dataclass
class Retrieval:
    hits: list[Hit]  # every fused chunk candidate, best first
    sections: list[SectionPick]  # best first
    sources: list[Source]  # what the LLM gets, in prompt order


def retrieve(db: Session, owner_id: str, question: str, document_ids: list[uuid.UUID] | None) -> list[Source]:
    return retrieve_context(db, owner_id, question, document_ids).sources


def retrieve_context(db: Session, owner_id: str, question: str, document_ids: list[uuid.UUID] | None) -> Retrieval:
    """Hierarchical retrieval: search finds chunks, but the LLM gets whole sections.

    1. The top RETRIEVAL_TOP_K fused chunk hits above the similarity floor, plus
       the sections whose own embedding matches the question (above the floor),
       vote for top-level sections: a section scores the sum of its hits' RRF
       scores plus an RRF term for its section-embedding rank.
    2. Sections are taken best first. One that fits RETRIEVAL_TOKEN_BUDGET goes in
       whole, in document order, so "VOTOCAST's obligations" brings every clause of
       that section even if only one of them ranked. A section too big for what's
       left contributes only its hit chunks (or, matched by its embedding alone,
       its first chunks).

    The floor applies to keyword hits too, so a lone keyword match can't turn an
    unanswerable question into an answer."""
    settings = get_settings()
    if not _has_chunks(db, owner_id, document_ids):
        return Retrieval([], [], [])
    query_embedding = ai.embed_query(question)
    hits = search(db, owner_id, question, document_ids, query_embedding)
    seeds = [h for h in hits if h.source.similarity >= settings.retrieval_min_similarity][: settings.retrieval_top_k]

    section_distance = Section.embedding.cosine_distance(query_embedding)
    section_query = select(Section.id, section_distance).where(Section.owner_id == owner_id)
    if document_ids is not None:
        section_query = section_query.where(Section.document_id.in_(document_ids))
    section_matches = [
        (section_id, 1 - dist)
        for section_id, dist in db.execute(
            section_query.order_by(section_distance).limit(settings.retrieval_section_candidates)
        )
        if 1 - dist >= settings.retrieval_min_similarity
    ]

    # Chunks indexed before sections existed (section_id NULL) stand alone.
    scores: dict[uuid.UUID, float] = {}
    for hit in seeds:
        key = hit.source.section_id or hit.source.chunk_id
        scores[key] = scores.get(key, 0.0) + hit.rrf_score
    section_similarity = dict(section_matches)
    for rank, (section_id, _) in enumerate(section_matches, start=1):
        scores[section_id] = scores.get(section_id, 0.0) + 1 / (RRF_K + rank)
    if not scores:
        return Retrieval(hits, [], [])

    rows = db.execute(
        select(Chunk, Document.filename, Chunk.embedding.cosine_distance(query_embedding))
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.owner_id == owner_id, Chunk.section_id.in_(scores))
        .order_by(Chunk.chunk_index)
    ).all()
    members: dict[uuid.UUID, list[Source]] = {}
    for chunk, filename, dist in rows:
        members.setdefault(chunk.section_id, []).append(_source(chunk, filename, 1 - dist))
    for hit in seeds:
        if hit.source.section_id is None:
            members[hit.source.chunk_id] = [hit.source]
    paths = dict(db.execute(select(Section.id, Section.heading_path).where(Section.id.in_(scores))).tuples().all())

    seed_ids = {h.source.chunk_id for h in seeds}
    hit_counts: dict[uuid.UUID, int] = {}
    for hit in seeds:
        if hit.source.section_id is not None:
            hit_counts[hit.source.section_id] = hit_counts.get(hit.source.section_id, 0) + 1
    labels = {key: path.rsplit(" > ", 1)[-1] for key, path in paths.items() if path}
    lexemes = _lexemes(db, [question, *labels.values()])
    question_lexemes, label_lexemes = lexemes[0], dict(zip(labels, lexemes[1:]))
    leader = None
    if section_matches and (
        len(section_matches) == 1 or section_matches[0][1] - section_matches[1][1] >= SECTION_EMBEDDING_LEAD
    ):
        leader = section_matches[0][0]

    budget = settings.retrieval_token_budget
    sources: list[Source] = []
    picks: list[SectionPick] = []
    for key in sorted(scores, key=scores.__getitem__, reverse=True):
        chunks = members.get(key, [])
        if not chunks:
            continue
        hit_chunks = [c for c in chunks if c.chunk_id in seed_ids]
        reason = _expand_reason(
            hit_counts.get(key, 0),
            labels.get(key),
            label_lexemes.get(key, set()),
            question,
            question_lexemes,
            key == leader,
        )
        if reason and sum(c.token_count for c in chunks) <= budget:
            candidates = chunks
        else:
            # Too big to send whole: its hits, or its opening chunks if it was
            # picked by its own embedding alone.
            candidates = hit_chunks or (chunks if reason else [])
            if candidates is not chunks:
                reason = None
        chosen = []
        for chunk in candidates:
            if chunk.token_count <= budget:
                chosen.append(chunk)
                budget -= chunk.token_count
        for chunk in chosen:
            chunk.match = "hit" if chunk.chunk_id in seed_ids else "section"
        sources.extend(chosen)
        picks.append(
            SectionPick(
                paths.get(key, chunks[0].heading_path),
                chunks[0].document_name,
                scores[key],
                section_similarity.get(key),
                len(chunks),
                len(chosen),
                reason,
            )
        )
    return Retrieval(hits, picks, sources)


def _expand_reason(
    hit_count: int,
    label: str | None,
    label_lexemes: set[str],
    question: str,
    question_lexemes: set[str],
    is_leading_section_match: bool,
) -> str | None:
    """Why a section should be sent whole, or None to send only its hit chunks."""
    if hit_count >= SECTION_MIN_HITS:
        return f"{hit_count} hits"
    if label:
        words = {lexeme for lexeme in label_lexemes if not lexeme.isdigit()}
        if words and len(words & question_lexemes) / len(words) >= SECTION_HEADING_OVERLAP:
            return "heading"
        if (match := _SECTION_NUMBER_RE.match(label)) and re.search(
            rf"(?i)\b(?:section|article|clause|§)\s*{re.escape(match.group(1))}\b(?![.\d])", question
        ):
            return "section number"
    if is_leading_section_match:
        return "section embedding"
    return None


def _lexemes(db: Session, texts: list[str]) -> list[set[str]]:
    """Postgres' English lexemes for each text: stemmed, stop words removed."""
    return [set(row) for row in db.scalars(_LEXEMES_SQL, {"texts": texts})]


def _has_chunks(db: Session, owner_id: str, document_ids: list[uuid.UUID] | None) -> bool:
    query = select(Chunk.id).where(Chunk.owner_id == owner_id)
    if document_ids is not None:
        query = query.where(Chunk.document_id.in_(document_ids))
    return db.scalar(query.limit(1)) is not None


def _source(chunk: Chunk, filename: str, similarity: float) -> Source:
    return Source(
        chunk.id,
        chunk.document_id,
        filename,
        chunk.page_start,
        chunk.section,
        chunk.heading_path,
        chunk.content,
        page_end=chunk.page_end,
        element_type=chunk.element_type,
        text_source=chunk.source,
        bboxes=chunk.bboxes,
        similarity=similarity,
        section_id=chunk.section_id,
        chunk_index=chunk.chunk_index,
        token_count=chunk.token_count or 0,
    )


def search(
    db: Session,
    owner_id: str,
    question: str,
    document_ids: list[uuid.UUID] | None,
    query_embedding: list[float] | None = None,
) -> list[Hit]:
    """All vector and full-text chunk candidates fused with reciprocal rank fusion,
    best first, unfiltered. Full-text catches exact terms ("Schedule B", "2.6")
    that embeddings miss."""
    settings = get_settings()

    def scoped(query):
        query = query.where(Chunk.owner_id == owner_id)
        if document_ids is not None:
            query = query.where(Chunk.document_id.in_(document_ids))
        return query

    # Skip the embedding call entirely when there is nothing to search.
    if query_embedding is None:
        if not _has_chunks(db, owner_id, document_ids):
            return []
        query_embedding = ai.embed_query(question)

    # With owner/document filters, a plain HNSW scan can return fewer rows than
    # the limit; iterative scan (pgvector >= 0.8) keeps searching until it has them.
    db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    distance = Chunk.embedding.cosine_distance(query_embedding)
    vector_ids = db.scalars(
        scoped(select(Chunk.id)).order_by(distance).limit(settings.retrieval_candidates)
    ).all()

    text_ids = bm25_search(db, owner_id, question, document_ids, settings.retrieval_candidates)

    vector_rank = {chunk_id: rank for rank, chunk_id in enumerate(vector_ids, start=1)}
    text_rank = {chunk_id: rank for rank, chunk_id in enumerate(text_ids, start=1)}
    scores = {
        chunk_id: sum(1 / (RRF_K + ranks[chunk_id]) for ranks in (vector_rank, text_rank) if chunk_id in ranks)
        for chunk_id in vector_rank | text_rank
    }

    rows = db.execute(
        select(Chunk, Document.filename, distance.label("distance"))
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.id.in_(scores))
    ).all()
    hits = [
        Hit(
            _source(chunk, filename, 1 - dist),
            vector_rank=vector_rank.get(chunk.id),
            text_rank=text_rank.get(chunk.id),
            rrf_score=scores[chunk.id],
        )
        for chunk, filename, dist in rows
    ]
    return sorted(hits, key=lambda h: h.rrf_score, reverse=True)


def bm25_search(
    db: Session, owner_id: str, question: str, document_ids: list[uuid.UUID] | None, limit: int
) -> list[uuid.UUID]:
    """Chunk ids ranked by BM25 over the owner's chunks (or just `document_ids`)."""
    return list(
        db.scalars(
            _BM25_SQL,
            {
                "question": question,
                "owner_id": owner_id,
                "document_ids": document_ids,
                "heading_boost": BM25_HEADING_BOOST,
                "k1": BM25_K1,
                "b": BM25_B,
                "limit": limit,
            },
        )
    )


def _user_prompt(question: str, sources: list[Source]) -> str:
    parts = []
    for n, source in enumerate(sources, start=1):
        location = ", ".join(
            filter(None, [source.document_name, f"page {source.page}" if source.page else None, source.heading_path])
        )
        parts.append(f"[{n}] ({location})\n{source.content}")
    return "Sources:\n\n" + "\n\n".join(parts) + f"\n\nQuestion: {question}"


def _normalize(text: str) -> str:
    return " ".join(text.split())


def build_answer(raw: dict, sources: list[Source]) -> ChatAnswer:
    """Keep only citations whose quote appears verbatim in the cited source, and
    renumber markers so [n] points at citations[n-1]. No verified citation means
    the answer is unsupported, so it's reported as insufficient evidence."""
    answer = (raw.get("answer") or "").strip()
    if raw.get("insufficient_evidence") or not answer:
        return insufficient(sources)

    verified_quotes: dict[int, str] = {}
    for citation in raw.get("citations") or []:
        n, quote = citation.get("source"), _normalize(citation.get("quote") or "")
        if isinstance(n, int) and 1 <= n <= len(sources) and quote and n not in verified_quotes:
            if quote in _normalize(sources[n - 1].content):
                verified_quotes[n] = quote

    citations: list[Citation] = []
    renumber: dict[int, int] = {}

    def replace(match: re.Match) -> str:
        kept = []
        for n in (int(x) for x in match.group(1).split(",")):
            if n not in verified_quotes:
                continue
            if n not in renumber:
                source = sources[n - 1]
                citations.append(Citation(**_location(source), quote=verified_quotes[n]))
                renumber[n] = len(citations)
            kept.append(renumber[n])
        return "".join(f"[{k}]" for k in dict.fromkeys(kept))

    answer = _normalize_spacing(_MARKER_RE.sub(replace, answer))
    if not citations:
        return insufficient(sources)
    return ChatAnswer(
        answer=answer,
        citations=citations,
        sources=[_source_out(s, renumber.get(n)) for n, s in enumerate(sources, start=1)],
        insufficient_evidence=False,
    )


def _location(source: Source) -> dict:
    return {
        "id": str(source.chunk_id),
        "document_id": str(source.document_id),
        "document_name": source.document_name,
        "page": source.page,
        "page_end": source.page_end,
        "section": source.section,
        "heading_path": source.heading_path,
        "element_type": source.element_type,
        "text_source": source.text_source,
        # Chunks indexed before parser_version 3 store boxes in PDF points with a
        # bottom-left origin and no page size; those can't be placed, so skip them.
        "bboxes": [b for b in source.bboxes or [] if "x" in b],
    }


def _source_out(source: Source, citation: int | None) -> schemas.Source:
    return schemas.Source(
        **_location(source),
        content=source.content,
        similarity=round(source.similarity, 4),
        citation=citation,
        match=source.match,
    )


def _normalize_spacing(text: str) -> str:
    # Removing unverified markers can leave "word ." or trailing spaces behind.
    # Leading spaces are kept: they indent Markdown sub-lists.
    text = re.sub(r"(?<=\S)[ \t]{2,}", " ", text)
    text = re.sub(r"(?<=\S)[ \t]+([.,;:])", r"\1", text)
    return re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE).strip()
