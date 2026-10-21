"""Query analysis before retrieval: one LLM call (QUERY_ANALYSIS_MODEL) that splits
a question into what each retrieval step needs.

- `contracts`: how the question names specific contracts (parties, titles). They
  pick the documents to search (resolve_documents) instead of being search terms:
  on the CUAD evaluation, BM25 over "In the agreement between Honeywell and
  Garrett, ..." ranked the preamble and signature blocks, where the party names
  are, above the clause asked about.
- `clause_refs` and `keywords`: clause numbers and exact defined terms, the only
  input to BM25. Without them retrieval is vector-only (BM25 added nothing on
  questions scoped to one contract).
- `search_query`: the question restated as the clause that would answer it,
  without the names and in contract wording, for the embedding.

If the call fails or returns nothing usable, the question is searched as typed."""

import logging
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai
from app.config import get_settings
from app.models import Chunk

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You prepare a user's question about their contracts for a search engine. Don't answer it.

Return JSON with:
- "contracts": each way the question identifies a specific contract, copied as written: party names, contract titles, dates ("the co-hosting agreement between Software.net and Networks Associates" -> ["Software.net", "Networks Associates", "co-hosting agreement"]). Empty when it names none; "this agreement" or "the contract" alone names none.
- "clause_refs": clause, section, article, schedule or exhibit numbers in the question, as written ("2.6", "Section 14.3", "Schedule B").
- "keywords": exact terms that must appear literally: quoted text and capitalized defined terms ("Licensed Intellectual Property", "Change of Control"). Not party names, not ordinary words. Usually empty.
- "search_query": one or two sentences describing the contract clause that would answer the question, in the wording contracts use, with the usual alternative phrasings (for exclusivity: "exclusive", "sole provider", "shall not sell to any third party"). Never include party names or contract titles in it.

Example: "In the supply agreement between Acme Corp and Beta LLC, can Acme terminate without cause?" ->
{"contracts": ["supply agreement", "Acme Corp", "Beta LLC"], "clause_refs": [], "keywords": [], "search_query": "Either party may terminate this agreement for convenience, without cause, upon written notice to the other party."}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "contracts": {"type": "array", "items": {"type": "string"}},
        "clause_refs": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "search_query": {"type": "string"},
    },
    "required": ["contracts", "clause_refs", "keywords", "search_query"],
    "additionalProperties": False,
}

# Analysis is a short extraction; past this the question is searched as typed
# (a thinking model can otherwise stall a request for minutes).
ANALYSIS_TIMEOUT_SECONDS = 30

# A contract name resolves to a document when that document holds at least this
# share of its BM25 hits (weighted by 1/rank); otherwise it's too ambiguous to scope.
RESOLVE_CANDIDATES = 20
RESOLVE_MIN_SHARE = 0.5


@dataclass
class QueryAnalysis:
    question: str
    search_query: str
    contracts: list[str] = field(default_factory=list)
    clause_refs: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    analyzed: bool = False  # False: the question as typed, nothing extracted

    @property
    def bm25_query(self) -> str | None:
        """Text for BM25: the exact terms when analyzed (None skips BM25), else the question."""
        if not self.analyzed:
            return self.question
        terms = [*self.clause_refs, *self.keywords]
        return " ".join(terms) if terms else None

    @property
    def expansion_text(self) -> str:
        """What section headings and numbers are matched against (rag._expand_reason)."""
        return " ".join([self.question, *([self.search_query] if self.analyzed else []), *self.clause_refs])


def unanalyzed(question: str) -> QueryAnalysis:
    return QueryAnalysis(question=question, search_query=question)


def analyze(question: str) -> QueryAnalysis:
    settings = get_settings()
    if not settings.query_analysis:
        return unanalyzed(question)
    try:
        raw = ai.complete_json(
            SYSTEM_PROMPT,
            f"Question: {question}",
            SCHEMA,
            name="analyze_query",
            model=settings.query_analysis_model,
            temperature=0,
            timeout=ANALYSIS_TIMEOUT_SECONDS,
        )
    except Exception:
        log.exception("Query analysis failed; searching the question as typed")
        return unanalyzed(question)

    def strings(key: str) -> list[str]:
        return [s.strip() for s in raw.get(key) or [] if isinstance(s, str) and s.strip()]

    contracts = strings("contracts")
    search_query = _without_names((raw.get("search_query") or "").strip(), contracts)
    if not search_query:
        return unanalyzed(question)
    return QueryAnalysis(
        question=question,
        search_query=search_query,
        contracts=contracts,
        clause_refs=strings("clause_refs"),
        keywords=strings("keywords"),
        analyzed=True,
    )


def _without_names(search_query: str, contracts: list[str]) -> str:
    """Removes the contract names from the search query, which small models leave in
    despite the prompt: with them, the embedding matches the preamble (where the
    names are) more than the clause. Also drops what that leaves dangling ("between and").
    Only names with a capital letter: generic ones ("agreement") are left in."""
    for name in sorted((c for c in contracts if c != c.lower()), key=len, reverse=True):
        search_query = re.sub(re.escape(name), " ", search_query, flags=re.IGNORECASE)
    search_query = re.sub(r"\b(?:between|of|by|with)(?:\s*(?:,|and|the)\s*)*(?=\s*(?:[.,;:?]|$))", " ", search_query)
    search_query = re.sub(r"\s+([.,;:?])", r"\1", re.sub(r"\s{2,}", " ", search_query))
    return search_query.strip(" ,;:")


def resolve_documents(
    db: Session, owner_id: str, contracts: list[str], document_ids: list[uuid.UUID] | None
) -> list[uuid.UUID] | None:
    """The documents the contract names point to, within `document_ids` (None: all of
    the owner's). BM25 does well here: party names are rare terms. Returns None when
    nothing resolves clearly, so the search keeps its original scope."""
    from app.rag import bm25_search  # rag imports this module

    if not contracts:
        return None
    weights: dict[uuid.UUID, float] = defaultdict(float)
    chunk_ids = bm25_search(db, owner_id, " ".join(contracts), document_ids, RESOLVE_CANDIDATES)
    if not chunk_ids:
        return None
    document_of = dict(db.execute(select(Chunk.id, Chunk.document_id).where(Chunk.id.in_(chunk_ids))).all())
    for rank, chunk_id in enumerate(chunk_ids, start=1):
        weights[document_of[chunk_id]] += 1 / rank
    total = sum(weights.values())
    best = max(weights, key=weights.__getitem__)
    if weights[best] / total < RESOLVE_MIN_SHARE:
        return None
    return [best]
