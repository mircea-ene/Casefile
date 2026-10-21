"""Evaluation on CUAD (https://www.atticusprojectai.org/cuad, CC BY 4.0).

    python -m app.evaluate build                 # pick contracts, write eval/questions.jsonl
    python -m app.evaluate upload                # upload them for the eval owner (the worker indexes them)
    python -m app.evaluate status                # indexing progress
    python -m app.evaluate run NAME [--retrieval-only] [--unscoped] [--retrieval MODE]
                                    [--no-analysis] [--limit N]
    python -m app.evaluate judge NAME            # LLM verdicts on the answers (JUDGE_MODEL)
    python -m app.evaluate report NAME           # metrics, also written to eval/runs/NAME/summary.json

CUAD has 510 contracts with lawyer-labelled spans for 41 clause categories. `build`
picks EVAL_CONTRACTS of them (EVAL_MIN_PAGES-EVAL_MAX_PAGES pages, spread over
contract types) and asks one question per category in CATEGORIES, scoped to that
contract with `document_ids`. A category with no labelled span is a question the
contract can't answer, so the right result there is a refusal (or an answer saying
the clause is absent).

Documents belong to EVAL_OWNER, not a Cognito user, so they don't show in anyone's
UI. Spans point into CUAD's .txt files while chunks come from the PDFs, so passages
are matched by word overlap (_covers), not by offsets.

`run` calls the same steps as `answer_question` (retrieve_context, the LLM call,
build_answer) so it can also record the hit ranking and the citations the
verifier dropped. It appends to results.jsonl and skips questions already there,
so an interrupted run continues where it stopped.

`--unscoped` searches all eval contracts instead of the one the question is about
(a harder retrieval problem: the right clause has to win against the same clause
type in 39 other contracts). The question then names the contract, from
CONTRACT_REFS_FILE: "In the co-hosting agreement between A and B, can a party ...". Gold passages only count in chunks of the question's
own contract. `--retrieval` runs an ablation (RETRIEVAL_MODES)."""

import argparse
import json
from contextlib import contextmanager
import random
import re
import time
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func, select

from app import ai, rag, storage, tracing
from app.config import PROJECT_ROOT, get_settings
from app.db import SessionLocal
from app.models import Document, DocumentStatus

CUAD_DIR = PROJECT_ROOT / "CUAD_v1"
EVAL_DIR = PROJECT_ROOT / "eval"
QUESTIONS_FILE = EVAL_DIR / "questions.jsonl"
# Contract title -> how a user would name it ("the co-hosting agreement between A and B"),
# for unscoped questions. Built from CUAD's Document Name and Parties labels, hand-checked.
CONTRACT_REFS_FILE = EVAL_DIR / "contracts.json"
RUNS_DIR = EVAL_DIR / "runs"

EVAL_OWNER = "eval-cuad"
EVAL_CONTRACTS = 40
EVAL_MIN_PAGES = 5
EVAL_MAX_PAGES = 30
EVAL_SEED = 7

# A different model from the one answering, so it doesn't grade its own output.
JUDGE_MODEL = "qwen/qwen3.6-35b-a3b"

# CUAD category -> the question asked. Phrased the way a user would ask, but
# covering what CUAD's definition counts (its "Details" text).
CATEGORIES = {
    "Governing Law": "Which state's or country's law governs this agreement?",
    "Expiration Date": "When does the initial term of this agreement expire?",
    "Renewal Term": "Does this agreement renew or extend after its initial term, and for how long?",
    "Termination For Convenience": "Can either party terminate this agreement without cause, just by giving notice?",
    "Non-Compete": (
        "Is either party restricted from competing with the other, or from operating in a certain "
        "territory, business or technology sector?"
    ),
    "Exclusivity": (
        "Does this agreement contain an exclusivity commitment, such as exclusive dealing, buying all "
        "requirements from one party, or a ban on selling to or working with third parties?"
    ),
    "Change Of Control": (
        "What happens if a party undergoes a change of control, such as a merger or a sale of substantially "
        "all of its assets? Is consent or notice required, or can the other party terminate?"
    ),
    "Anti-Assignment": "Can a party assign this agreement to a third party, or is consent or notice required?",
    "Ip Ownership Assignment": (
        "Does intellectual property created by one party become the property of the other party?"
    ),
    "Audit Rights": "Does a party have the right to audit the other party's books, records or premises?",
    "Cap On Liability": (
        "Is a party's liability capped or limited, for example by a maximum amount or a time limit for "
        "bringing claims?"
    ),
    "Most Favored Nation": (
        "Is there a most-favored-nation clause, entitling a party to better terms that are given to a third party?"
    ),
    "Liquidated Damages": "Does this agreement provide for liquidated damages or a termination fee?",
}

# Passage matching: words are lowercase alphanumeric runs, compared as 4-word shingles.
SHINGLE = 4
# A chunk counts as containing a gold span when it holds this share of the span's
# shingles (spans can straddle two chunks).
CHUNK_COVERAGE = 0.3
# A citation quote is on a gold span when this share of its shingles is in one.
QUOTE_COVERAGE = 0.5

_WORD_RE = re.compile(r"[a-z0-9]+")

# Retrieval ablations: "hybrid" is the app as it is; "vector" / "bm25" keep only
# one side of the fusion; "no-sections" sends only the top-k hit chunks (no whole
# sections, no section-embedding picks).
RETRIEVAL_MODES = ("hybrid", "vector", "bm25", "no-sections")


# --- passage matching ---------------------------------------------------------


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _shingles(words: list[str]) -> set[tuple[str, ...]]:
    if len(words) < SHINGLE:
        return {tuple(words)} if words else set()
    return {tuple(words[i : i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}


def _contains(haystack: list[str], needle: list[str]) -> bool:
    return f" {' '.join(needle)} " in f" {' '.join(haystack)} "


def _covers(text: str, span: str, threshold: float) -> bool:
    """Whether `text` contains enough of `span` (by 4-word shingles; short spans whole)."""
    text_words, span_words = _words(text), _words(span)
    if not span_words:
        return False
    if len(span_words) < SHINGLE:
        return _contains(text_words, span_words)
    span_shingles = _shingles(span_words)
    return len(span_shingles & _shingles(text_words)) / len(span_shingles) >= threshold


def _quote_on_gold(quote: str, spans: list[str]) -> bool:
    """Whether a citation quote lies (mostly) inside one of the gold spans."""
    quote_words = _words(quote)
    if not quote_words:
        return False
    if len(quote_words) < SHINGLE:
        return any(_contains(_words(s), quote_words) for s in spans)
    quote_shingles = _shingles(quote_words)
    return any(
        len(quote_shingles & _shingles(_words(s))) / len(quote_shingles) >= QUOTE_COVERAGE for s in spans
    )


# --- build --------------------------------------------------------------------


def _contract_type(pdf: Path) -> str:
    """Folder name normalized: "Joint Venture _ Filing", "License_Agreements" -> "joint venture", "license"."""
    name = pdf.parent.name.lower().replace("_", " ")
    name = re.sub(r"\b(agreements?|filing)\b", "", name)
    return " ".join(name.split())


def build(_: argparse.Namespace) -> None:
    import pypdfium2 as pdfium

    pdfs = {p.stem: p for p in (CUAD_DIR / "full_contract_pdf").rglob("*") if p.suffix.lower() == ".pdf"}
    cuad = json.loads((CUAD_DIR / "CUAD_v1.json").read_text())
    contracts = {}
    for entry in cuad["data"]:
        pdf = pdfs.get(entry["title"])
        if pdf is None:
            continue
        pages = len(pdfium.PdfDocument(str(pdf)))
        if EVAL_MIN_PAGES <= pages <= EVAL_MAX_PAGES:
            contracts[entry["title"]] = (pdf, pages, entry["paragraphs"][0]["qas"])

    # Round-robin over contract types, so the common ones (licenses, co-branding)
    # don't crowd out the rest.
    rng = random.Random(EVAL_SEED)
    by_type: dict[str, list[str]] = defaultdict(list)
    for title in sorted(contracts):
        by_type[_contract_type(contracts[title][0])].append(title)
    for titles in by_type.values():
        rng.shuffle(titles)
    types = sorted(by_type)
    rng.shuffle(types)
    chosen: list[str] = []
    while len(chosen) < EVAL_CONTRACTS and any(by_type.values()):
        for kind in types:
            if by_type[kind] and len(chosen) < EVAL_CONTRACTS:
                chosen.append(by_type[kind].pop())

    EVAL_DIR.mkdir(exist_ok=True)
    count = Counter()
    with QUESTIONS_FILE.open("w") as out:
        for title in sorted(chosen):
            pdf, pages, qas = contracts[title]
            spans_by_category = {q["id"].split("__")[-1]: [a["text"] for a in q["answers"]] for q in qas}
            for category, question in CATEGORIES.items():
                spans = list(dict.fromkeys(s.strip() for s in spans_by_category.get(category, []) if s.strip()))
                record = {
                    "id": f"{title}__{category}",
                    "contract": title,
                    "pdf": str(pdf.relative_to(CUAD_DIR)),
                    "pages": pages,
                    "contract_type": _contract_type(pdf),
                    "category": category,
                    "question": question,
                    "answerable": bool(spans),
                    "gold_spans": spans,
                }
                out.write(json.dumps(record) + "\n")
                count[record["answerable"]] += 1
    print(
        f"{len(chosen)} contracts, {sum(count.values())} questions "
        f"({count[True]} answerable, {count[False]} not) -> {QUESTIONS_FILE.relative_to(PROJECT_ROOT)}"
    )


def _questions() -> list[dict]:
    return [json.loads(line) for line in QUESTIONS_FILE.read_text().splitlines() if line.strip()]


def _contracts(questions: list[dict]) -> dict[str, str]:
    """Contract title -> PDF path relative to CUAD_DIR."""
    return {q["contract"]: q["pdf"] for q in questions}


def _filename(pdf: str) -> str:
    return Path(pdf).name


# --- upload / status ----------------------------------------------------------


def upload(_: argparse.Namespace) -> None:
    """Same steps as POST /documents: commit the row as processing, then put the file
    under the upload prefix, which queues it for the worker."""
    settings = get_settings()
    contracts = _contracts(_questions())
    with SessionLocal() as db:
        existing = set(db.scalars(select(Document.filename).where(Document.owner_id == EVAL_OWNER)))
        uploaded = 0
        for pdf in contracts.values():
            filename = _filename(pdf)
            if filename in existing:
                continue
            path = CUAD_DIR / pdf
            document_id = uuid.uuid4()
            document = Document(
                id=document_id,
                owner_id=EVAL_OWNER,
                filename=filename,
                content_type="application/pdf",
                size_bytes=path.stat().st_size,
                storage_key=f"{settings.s3_upload_prefix}{EVAL_OWNER}/{document_id}.pdf",
                status=DocumentStatus.PROCESSING,
            )
            db.add(document)
            db.commit()
            with path.open("rb") as file:
                storage.save_file(document.storage_key, file, document.content_type)
            uploaded += 1
    print(f"Uploaded {uploaded} contract(s); {len(contracts) - uploaded} were already there")


def status(_: argparse.Namespace) -> None:
    with SessionLocal() as db:
        rows = db.execute(
            select(Document.status, func.count())
            .where(Document.owner_id == EVAL_OWNER)
            .group_by(Document.status)
        ).all()
        failed = db.execute(
            select(Document.filename, Document.error).where(
                Document.owner_id == EVAL_OWNER, Document.status == DocumentStatus.FAILED
            )
        ).all()
    print(", ".join(f"{n} {s}" for s, n in sorted(rows)) or "no eval documents")
    for filename, error in failed:
        print(f"  failed: {filename}: {error}")


# --- run ----------------------------------------------------------------------


def _run_dir(name: str) -> Path:
    return RUNS_DIR / name


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    settings.query_analysis = settings.query_analysis and not args.no_analysis
    questions = _questions()
    if args.category:
        questions = [q for q in questions if q["category"] in args.category]

    run_dir = _run_dir(args.name)
    run_dir.mkdir(parents=True, exist_ok=True)
    config_file = run_dir / "config.json"
    config = {
        "llm_model": settings.llm_model,
        "embedding_model": settings.embedding_model,
        "retrieval_top_k": settings.retrieval_top_k,
        "retrieval_min_similarity": settings.retrieval_min_similarity,
        "retrieval_token_budget": settings.retrieval_token_budget,
        "retrieval_only": args.retrieval_only,
        "unscoped": args.unscoped,
        "retrieval_mode": args.retrieval,
        "query_analysis": settings.query_analysis,
        "query_analysis_model": settings.query_analysis_model or settings.llm_model if settings.query_analysis else None,
    }
    if config_file.exists() and json.loads(config_file.read_text()) | {"started": None} != config | {"started": None}:
        raise SystemExit(f"{run_dir} was started with other settings; use a new run name")
    if not config_file.exists():
        config_file.write_text(json.dumps(config | {"started": datetime.now(UTC).isoformat()}, indent=2) + "\n")

    results_file = run_dir / "results.jsonl"
    done = {r["id"] for r in _read_jsonl(results_file)}
    todo = [q for q in questions if q["id"] not in done]

    with SessionLocal() as db:
        documents = dict(
            db.execute(
                select(Document.filename, Document.id).where(
                    Document.owner_id == EVAL_OWNER, Document.status == DocumentStatus.READY
                )
            ).all()
        )
    missing = {q["contract"] for q in todo if _filename(q["pdf"]) not in documents}
    if missing:
        print(f"Skipping {len(missing)} contract(s) that aren't indexed (see `status`)")
        todo = [q for q in todo if q["contract"] not in missing]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(done)} done, {len(todo)} to go -> {results_file.relative_to(PROJECT_ROOT)}")
    with results_file.open("a") as out, _retrieval_mode(args.retrieval):
        for n, question in enumerate(todo, start=1):
            record = _run_one(
                question, documents[_filename(question["pdf"])], args.name, args.retrieval_only, args.unscoped
            )
            out.write(json.dumps(record) + "\n")
            out.flush()
            outcome = "retrieved" if args.retrieval_only else ("refused" if record["refused"] else "answered")
            print(
                f"[{n}/{len(todo)}] {record['latency_s']:6.1f}s  {outcome:<9}  "
                f"gold {'✓' if record['gold_retrieved'] else '✗' if question['answerable'] else '-'}  {question['id']}",
                flush=True,
            )
    tracing.shutdown()


@contextmanager
def _retrieval_mode(mode: str):
    """Patches app.rag for an ablation; retrieve_context looks both functions up at call time."""
    search, expand_reason = rag.search, rag._expand_reason

    def one_sided(*args, **kwargs):
        rank = "vector_rank" if mode == "vector" else "text_rank"
        hits = [h for h in search(*args, **kwargs) if getattr(h, rank) is not None]
        for hit in hits:
            hit.rrf_score = 1 / (rag.RRF_K + getattr(hit, rank))
        return sorted(hits, key=lambda h: h.rrf_score, reverse=True)

    if mode in ("vector", "bm25"):
        rag.search = one_sided
    elif mode == "no-sections":
        rag._expand_reason = lambda *args, **kwargs: None
    try:
        yield
    finally:
        rag.search, rag._expand_reason = search, expand_reason


@lru_cache
def _contract_refs() -> dict[str, str]:
    return json.loads(CONTRACT_REFS_FILE.read_text())


def _run_one(
    question: dict, document_id: uuid.UUID, run_name: str, retrieval_only: bool, unscoped: bool = False
) -> dict:
    spans = question["gold_spans"]
    asked = question["question"]
    if unscoped:
        asked = f"In {_contract_refs()[question['contract']]}, {asked[0].lower()}{asked[1:]}"
    started = time.monotonic()
    with tracing.trace(
        "eval", user_id=EVAL_OWNER, session_id=run_name, input=asked,
        metadata={"eval_id": question["id"][:200], "category": question["category"]},
    ) as root, SessionLocal() as db:
        retrieval = rag.retrieve_context(
            db, EVAL_OWNER, asked, None if unscoped else [document_id]
        )
        retrieval_s = time.monotonic() - started
        raw: dict = {}
        result = None
        if not retrieval_only:
            if retrieval.sources:
                raw = ai.complete_json(
                    rag.SYSTEM_PROMPT, rag._user_prompt(asked, retrieval.sources),
                    rag.ANSWER_SCHEMA, name="answer",
                )
                result = rag.build_answer(raw, retrieval.sources)
            else:
                result = rag.insufficient()
            root.update(output=result.answer or "(insufficient evidence)")

    # Rank (1-based) of the first hit holding a gold span, among the hits that picked sections.
    seeds = retrieval.seeds
    def is_gold(source: rag.Source) -> bool:
        return source.document_id == document_id and any(_covers(source.content, s, CHUNK_COVERAGE) for s in spans)

    first_gold_rank = next((rank for rank, h in enumerate(seeds, start=1) if is_gold(h.source)), None)
    own_sources = [s for s in retrieval.sources if s.document_id == document_id]
    sent_text = "\n".join(s.content for s in own_sources)
    spans_retrieved = [s for s in spans if _covers(sent_text, s, CHUNK_COVERAGE)]
    record = {
        "id": question["id"],
        "category": question["category"],
        "answerable": question["answerable"],
        "latency_s": round(time.monotonic() - started, 2),
        "retrieval_s": round(retrieval_s, 2),
        "sources_sent": len(retrieval.sources),
        "context_tokens": sum(s.token_count for s in retrieval.sources),
        # Share of the context from the question's own contract (1.0 when scoped).
        "own_contract_share": _share(sum(s.token_count for s in own_sources), sum(s.token_count for s in retrieval.sources)),
        "top_hit_own_contract": bool(seeds) and seeds[0].source.document_id == document_id,
        "top_similarity": round(max((h.source.similarity for h in retrieval.hits), default=0.0), 4),
        "first_gold_rank": first_gold_rank,
        "analysis": (
            {k: getattr(retrieval.analysis, k) for k in ("search_query", "contracts", "clause_refs", "keywords")}
            if retrieval.analysis is not None and retrieval.analysis.analyzed else None
        ),
        "scoped_to_own_contract": retrieval.document_ids == [document_id],
        "gold_spans": len(spans),
        "gold_spans_retrieved": len(spans_retrieved),
        "gold_retrieved": bool(spans_retrieved),
    }
    if result is None:
        return record

    raw_citations = [c for c in raw.get("citations") or [] if isinstance(c, dict)]
    citations = [
        {
            "quote": c.quote,
            "page": c.page,
            "heading_path": c.heading_path,
            "on_gold": _quote_on_gold(c.quote, spans),
            "chunk_on_gold": any(is_gold(s) for s in retrieval.sources if str(s.chunk_id) == c.id),
        }
        for c in result.citations
    ]
    return record | {
        "refused": result.insufficient_evidence,
        "model_refused": bool(raw.get("insufficient_evidence")) or not retrieval.sources,
        "answer": result.answer,
        "citations": citations,
        "raw_citations": len(raw_citations),
        "verified_citations": len(citations),
    }


# --- judge --------------------------------------------------------------------

JUDGE_SYSTEM = """You grade answers from a contract question-answering system against lawyer annotations from the CUAD dataset.

You get the question, CUAD's definition of the clause category, the passages the annotators marked in the contract for that category (or a note that they marked none), and the system's answer with its quoted citations.

Verdicts:
- "correct": the answer is consistent with the annotated passages and gets the substance right (who, what, how long, which law). For a question with no annotated passage, "correct" means the answer says the contract has no such clause, or describes something that clearly falls outside the category's definition.
- "partial": right in part, but it misses an important element of the annotated passages (another relevant clause, a condition, a party) or adds a minor inaccuracy.
- "incorrect": it contradicts the annotated passages, describes a different clause, or claims such a clause exists when the annotators marked none and the quotes don't show one that fits the definition.

Judge only against the annotations and the quotes, not outside knowledge. Keep "reason" to one sentence."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["correct", "partial", "incorrect"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}


def _cuad_definitions() -> dict[str, str]:
    cuad = json.loads((CUAD_DIR / "CUAD_v1.json").read_text())
    return {
        q["id"].split("__")[-1]: q["question"].split("Details:")[-1].strip()
        for q in cuad["data"][0]["paragraphs"][0]["qas"]
    }


def judge(args: argparse.Namespace) -> None:
    """Verdicts for answered questions only; refusals are scored without a judge."""
    run_dir = _run_dir(args.name)
    questions = {q["id"]: q for q in _questions()}
    definitions = _cuad_definitions()
    judgments_file = run_dir / "judgments.jsonl"
    done = {j["id"] for j in _read_jsonl(judgments_file)}
    todo = [r for r in _read_jsonl(run_dir / "results.jsonl") if r.get("refused") is False and r["id"] not in done]
    print(f"{len(done)} judged, {len(todo)} to go (judge: {args.model})")
    with judgments_file.open("a") as out:
        for n, result in enumerate(todo, start=1):
            question = questions[result["id"]]
            gold = (
                "\n\n".join(f"- {s}" for s in question["gold_spans"])
                if question["gold_spans"]
                else "(The annotators marked no passage for this category: the contract has no such clause.)"
            )
            quotes = "\n".join(f"- {c['quote']}" for c in result["citations"])
            prompt = (
                f"Question: {question['question']}\n\n"
                f"Category: {question['category']}: {definitions.get(question['category'], '')}\n\n"
                f"Annotated passages:\n{gold}\n\n"
                f"System answer:\n{result['answer']}\n\nQuotes it cited:\n{quotes}"
            )
            verdict = _judge_call(prompt, args.model)
            out.write(json.dumps({"id": result["id"], "judge_model": args.model} | verdict) + "\n")
            out.flush()
            print(f"[{n}/{len(todo)}] {verdict.get('verdict', '?'):<9}  {result['id']}", flush=True)


def _judge_call(prompt: str, model: str) -> dict:
    response = ai._client().chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_schema", "json_schema": {"name": "verdict", "strict": True, "schema": JUDGE_SCHEMA}},
        name="judge",
    )
    message = response.choices[0].message
    raw = message.content or getattr(message, "reasoning_content", None) or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"verdict": None, "reason": f"unparseable: {raw[:200]}"}


# --- report -------------------------------------------------------------------


def _share(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def _metrics(results: list[dict], judgments: dict[str, dict]) -> dict:
    answerable = [r for r in results if r["answerable"]]
    unanswerable = [r for r in results if not r["answerable"]]
    ranks = [r["first_gold_rank"] for r in answerable]
    metrics = {
        "questions": len(results),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        # Retrieval, on answerable questions.
        "recall_at_k": _share(sum(r is not None for r in ranks), len(ranks)),
        "mrr_at_k": round(sum(1 / r for r in ranks if r) / len(ranks), 3) if ranks else None,
        "gold_in_context": _share(sum(r["gold_retrieved"] for r in answerable), len(answerable)),
        "gold_span_recall": _share(
            sum(r["gold_spans_retrieved"] for r in answerable), sum(r["gold_spans"] for r in answerable)
        ),
        "mean_latency_s": round(sum(r["latency_s"] for r in results) / len(results), 1) if results else None,
        "mean_context_tokens": round(sum(r["context_tokens"] for r in results) / len(results)) if results else None,
        "top_hit_own_contract": _share(sum(r.get("top_hit_own_contract", True) for r in results), len(results)),
        "scoped_to_own_contract": _share(sum(r.get("scoped_to_own_contract", False) for r in results), len(results)),
    }
    if not results or "refused" not in results[0]:
        return metrics

    answered = [r for r in answerable if not r["refused"]]
    false_answers = [r for r in unanswerable if not r["refused"]]
    citations = [c for r in answered for c in r["citations"]]
    raw = sum(r["raw_citations"] for r in results if not r["model_refused"])
    verified = sum(r["verified_citations"] for r in results if not r["model_refused"])
    # Answers the verifier turned into refusals: the model answered, no quote survived.
    verifier_refusals = sum(r["refused"] and not r["model_refused"] for r in results)

    def verdict_share(rows: list[dict], verdict: str) -> float | None:
        judged = [judgments[r["id"]] for r in rows if r["id"] in judgments]
        return _share(sum(j.get("verdict") == verdict for j in judged), len(judged))

    sorted_latency = sorted(r["latency_s"] for r in results)
    metrics |= {
        "p95_latency_s": sorted_latency[int(0.95 * (len(sorted_latency) - 1))],
        # Answering.
        "answer_rate": _share(len(answered), len(answerable)),
        "refusal_rate_unanswerable": _share(len(unanswerable) - len(false_answers), len(unanswerable)),
        "citations_verified": _share(verified, raw),
        "verifier_refusals": verifier_refusals,
        # On answered, answerable questions: quotes inside a gold span, and answers citing a gold chunk.
        "citations_on_gold": _share(sum(c["on_gold"] for c in citations), len(citations)),
        "answers_citing_gold": _share(
            sum(any(c["chunk_on_gold"] for c in r["citations"]) for r in answered), len(answered)
        ),
        # Judge, on answered questions.
        "judged": sum(r["id"] in judgments for r in answerable + false_answers),
        "answered_correct": verdict_share(answered, "correct"),
        "answered_partial": verdict_share(answered, "partial"),
        "answered_incorrect": verdict_share(answered, "incorrect"),
        "false_answers_judged_correct": verdict_share(false_answers, "correct"),
    }
    # End to end on answerable questions: answered and judged correct.
    judged_answered = [r for r in answered if r["id"] in judgments]
    if judged_answered and len(judged_answered) == len(answered):
        metrics["answerable_correct"] = _share(
            sum(judgments[r["id"]].get("verdict") == "correct" for r in answered), len(answerable)
        )
    # Unanswerable questions handled correctly: refused, or answered and judged correct.
    if all(r["id"] in judgments for r in false_answers):
        metrics["unanswerable_handled"] = _share(
            len(unanswerable) - len(false_answers)
            + sum(judgments[r["id"]].get("verdict") == "correct" for r in false_answers),
            len(unanswerable),
        )
    return metrics


def report(args: argparse.Namespace) -> None:
    run_dir = _run_dir(args.name)
    results = _read_jsonl(run_dir / "results.jsonl")
    judgments = {j["id"]: j for j in _read_jsonl(run_dir / "judgments.jsonl")}
    by_category = defaultdict(list)
    for r in results:
        by_category[r["category"]].append(r)
    summary = {
        "run": args.name,
        "config": json.loads((run_dir / "config.json").read_text()),
        "overall": _metrics(results, judgments),
        "by_category": {c: _metrics(rows, judgments) for c, rows in sorted(by_category.items())},
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    print(f"Run {args.name}: {summary['config']['llm_model']} / {summary['config']['embedding_model']}\n")
    for key, value in summary["overall"].items():
        print(f"  {key:<30} {value}")
    columns = ["recall_at_k", "gold_in_context", "answer_rate", "refusal_rate_unanswerable", "answered_correct"]
    print(f"\n  {'category':<28} {'n':>4} {'ans':>4} " + " ".join(f"{c[:12]:>12}" for c in columns))
    for category, metrics in summary["by_category"].items():
        cells = " ".join(f"{'' if metrics.get(c) is None else metrics[c]:>12}" for c in columns)
        print(f"  {category:<28} {metrics['questions']:>4} {metrics['answerable']:>4} {cells}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build").set_defaults(func=build)
    commands.add_parser("upload").set_defaults(func=upload)
    commands.add_parser("status").set_defaults(func=status)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("name")
    run_parser.add_argument("--retrieval-only", action="store_true", help="skip the LLM; retrieval metrics only")
    run_parser.add_argument("--unscoped", action="store_true", help="search all eval contracts, not just the question's")
    run_parser.add_argument("--retrieval", choices=RETRIEVAL_MODES, default="hybrid", help="retrieval ablation")
    run_parser.add_argument("--no-analysis", action="store_true", help="search questions as typed (no LLM call)")
    run_parser.add_argument("--limit", type=int)
    run_parser.add_argument("--category", action="append", help="only this category (repeatable)")
    run_parser.set_defaults(func=run)
    judge_parser = commands.add_parser("judge")
    judge_parser.add_argument("name")
    judge_parser.add_argument("--model", default=JUDGE_MODEL)
    judge_parser.set_defaults(func=judge)
    report_parser = commands.add_parser("report")
    report_parser.add_argument("name")
    report_parser.set_defaults(func=report)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
