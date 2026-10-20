# Casefile

Ask your contracts. Every answer is cited to the clause.

Casefile is a document assistant for legal work. You upload contracts (PDF, DOCX, DOC, images, text), they are parsed and indexed clause by clause, and you ask questions in a chat. Each answer cites the passages it relies on, every citation is checked word for word against the source text, and clicking one opens the original PDF at that spot.

## Features

- **Clause-aware ingestion.** Docling extracts headings, paragraphs and tables with page positions; OCR runs only on regions without a text layer. Text is grouped into clauses by detecting clause numbers, not by fixed-size windows.
- **Hybrid, hierarchical retrieval.** Vector search (pgvector, HNSW) and BM25 (computed in SQL) are fused with reciprocal rank fusion. Sections with several hits, or whose heading or number matches the question, are sent whole, so "what are X's obligations" gets every clause of that section.
- **Verified citations.** The model returns an answer with `[n]` markers and a quote per source. Citations whose quote isn't found verbatim in the source are dropped; if none survive, the answer is reported as insufficient evidence instead.
- **Source viewer.** Each source carries its page and bounding boxes; the frontend opens the original file (presigned S3 URL) at the cited section.
- **Reliable indexing.** Upload to S3, EventBridge to SQS, and a worker that runs every job in its own process, extends message visibility while working, retries with back-off and dead-letters what keeps failing. Delivery is at least once, so indexing is idempotent.
- **Chat history.** Conversations are saved with LLM-generated titles that the user can rename.
- **Tracing.** Langfuse records every chat, indexing run and model call with token usage, per user and per conversation.
- **Auth.** Cognito JWTs; every query is scoped to the caller.

## Architecture

```
Browser (Next.js) ──► FastAPI ──► Postgres + pgvector (documents, chunks, sections, conversations)
     │                   │
     │ presigned URL     └──► S3 uploads/ ──► EventBridge ──► SQS ──► indexing worker
     └──────────────────────► S3                                     (Docling, chunking, embeddings)

LLM and embeddings: OpenAI-compatible API (LM Studio locally, Qwen3)
Tracing: Langfuse (ClickHouse, Redis, S3)
```

## Repository

| Path | What |
|---|---|
| `backend/` | FastAPI API and indexing worker (Python 3.13). Design and status in `backend/docs/IMPLEMENTATION.md`. |
| `frontend/` | Next.js app. API contract in `frontend/docs/backend-api.md`. |

## Running locally

Requirements: Docker, conda, Node.js, [LM Studio](https://lmstudio.ai) with an LLM and an embedding model loaded, and Floci (local AWS) with the S3 buckets, SQS queues, EventBridge rule and Cognito pool already created (Terraform, not part of this repo).

```bash
# Backend
cd backend
cp .env.example .env                                         # then fill in
cp docker/postgres/postgres.env.example docker/postgres/postgres.env
cp docker/langfuse/langfuse.env.example docker/langfuse/langfuse.env
docker compose up -d --wait        # Postgres + Langfuse (UI on http://localhost:3001)
conda create -n rag-backend python=3.13 && conda activate rag-backend
pip install -r requirements.txt
alembic upgrade head
fastapi dev main.py                # API on http://127.0.0.1:8000
python -m app.worker               # indexing worker, in a second terminal

# Frontend
cd frontend
cp .env.example .env.local
npm install
npm run dev                        # http://localhost:3000
```

Tests: `cd backend && pytest` (no database or model server needed).
