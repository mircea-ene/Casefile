# Casefile

Ask your contracts. Every answer is cited to the clause.

Casefile answers questions about your contracts. You upload them (PDF, DOCX, DOC, images or plain text), Casefile parses and indexes them clause by clause, and you ask questions in a chat. Each answer cites the passages it relies on. Every citation is checked word for word against the source text, and clicking one opens the original PDF at that spot.

## How it works

Docling extracts headings, paragraphs and tables along with their positions on the page. OCR runs only on regions that have no text layer. The text is then grouped into clauses by their clause numbers rather than cut into fixed-size windows.

Retrieval combines vector search (pgvector, HNSW) with BM25, which is computed in SQL, and merges the two rankings with reciprocal rank fusion. A section is sent to the model whole when it has several hits or when its heading or number matches the question. A question like "what are X's obligations" therefore gets every clause of that section.

The model answers with `[n]` markers and one quote per source. A citation is dropped if its quote can't be found verbatim in the source. If no citation is left, the response says there isn't enough evidence instead of answering.

Each source comes with its page and bounding boxes, and the frontend uses them to open the original file (through a presigned S3 URL) at the cited section.

Uploads go to S3, which sends an event through EventBridge to SQS. A worker runs each indexing job in its own process, extends the message's visibility while it works, retries with back-off and moves messages that keep failing to a dead-letter queue. SQS can deliver a message more than once, so indexing is idempotent.

Conversations are saved, and the LLM gives each one a title that the user can rename. Langfuse traces every chat, indexing run and model call, with token usage per user and per conversation. Users sign in through Cognito, and every query only sees the caller's own documents.

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

Backend, from the repository root:

```bash
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
```

Frontend, from the repository root:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev                        # http://localhost:3000
```

Tests: `cd backend && pytest` (no database or model server needed).
