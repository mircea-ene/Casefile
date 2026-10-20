# Casefile backend

The Casefile API and indexing worker, in Python 3.13 with FastAPI, SQLAlchemy and Postgres (pgvector). The API stores uploads, answers questions with verified citations and keeps the chat history. The worker parses and indexes documents from an SQS queue.

## How it works

### Indexing

1. `POST /documents` saves the document as `processing` and streams the file to S3 under `uploads/<owner>/<document id><ext>`.
2. S3 sends an "Object Created" event through EventBridge to the SQS queue.
3. `python -m app.worker` takes one message at a time and runs the job in a fresh child process. That way a crash or out-of-memory kill only fails that attempt, and a job that hangs is killed after `INDEX_TIMEOUT_SECONDS`. While the job runs, the worker keeps extending the message's visibility. Failed attempts are retried with back-off up to the queue's receive limit, after which the document is marked `failed` and the message moves to the dead-letter queue. SQS can deliver a message twice, so a document is only indexed while it is still `processing`, and the check is repeated under a row lock before writing.
4. Docling turns the file into headings, paragraphs and tables with page positions (`app/parsing.py`). PDFs are converted 25 pages at a time to bound memory, and OCR runs only where a page has no text layer (Apple Vision by default). Plain text and RTF are split into paragraphs directly.
5. The elements are grouped into clauses by their clause numbers (`app/chunking.py`). Each chunk is embedded together with its section breadcrumb, and each top-level section also gets its own embedding.
6. The chunks and sections are written, and the document set to `ready`, in a single commit.

### Answering

`POST /chat` (`app/rag.py`):

1. Retrieval runs a vector search (HNSW) and BM25 over the caller's chunks, with BM25 computed in SQL from a weighted `tsvector`. The two rankings are merged with reciprocal rank fusion, and chunks below a cosine similarity floor are dropped.
2. Sections are scored from their chunk hits and their own embeddings. A section is sent whole when it has two or more hits, when its heading matches the question, when the question names its number, or when its embedding clearly leads. Other sections only contribute the chunks that matched. Everything has to fit a token budget.
3. The LLM returns JSON with `[n]` markers and one quote per source. A citation is kept only if its quote appears verbatim in that source, and the markers are renumbered to match the citations that are left. If none survive, the response sets `insufficient_evidence`.
4. The response includes every source that was sent to the model, with its page, section path and bounding boxes, and which `[n]` cites it.

Each question and answer is saved as a turn in a conversation. The LLM titles new conversations in the background, and users can rename them.

### Other parts

- Auth (`app/auth.py`): Cognito access tokens verified against the pool's JWKS. Every query is scoped to the token's `sub`, and ids belonging to someone else return 404.
- Files: `GET /documents/{id}/file` returns a short-lived presigned S3 URL for the original.
- Tracing (`app/tracing.py`): Langfuse traces each chat, indexing run and title generation, per user and per conversation. Traces include the LLM and embedding calls with token counts, plus scores such as `cited_share` and `context_tokens`.
- Models (`app/ai.py`): any OpenAI-compatible API. Locally that's LM Studio with Qwen3 for chat and Qwen3-Embedding (truncated to 1024 dimensions) for embeddings.

## API

| Method and path | What |
|---|---|
| `GET /health` | Liveness |
| `GET /documents` / `POST /documents` | List / upload documents |
| `DELETE /documents/{id}` | Delete a document, its chunks and its file |
| `GET /documents/{id}/file` | Presigned URL for the original file |
| `POST /chat` | Ask a question, optionally limited to `document_ids` and continuing a `conversation_id` |
| `GET /conversations` / `GET /conversations/{id}` | Conversation list / one conversation with its turns |
| `PATCH /conversations/{id}` / `DELETE /conversations/{id}` | Rename / delete |

The request and response types are in `../frontend/lib/api.ts`.

## Running locally

This is the detailed version of steps 4 and 5 in the root README. It assumes LM Studio is serving both models and that Floci is running with the resources from `../infrastructure` (see its README).

### Prerequisites

- Docker, for Postgres and Langfuse.
- conda, for the Python 3.13 environment.
- LM Studio on `http://localhost:1234` with the LLM and embedding model from `.env` loaded (see the root README for the model requirements). Check with `curl http://localhost:1234/v1/models`.
- Floci on `http://localhost:4566` with the Cognito pool, the backend and Langfuse buckets, and the uploads queue created by Terraform.
- LibreOffice, only if you want to upload legacy `.doc` files.

### 1. Secrets for Postgres and Langfuse

```bash
cp docker/postgres/postgres.env.example docker/postgres/postgres.env
cp docker/langfuse/langfuse.env.example docker/langfuse/langfuse.env
```

In `docker/postgres/postgres.env`:

| Variable | Value |
|---|---|
| `POSTGRES_USER`, `POSTGRES_DB` | Keep `casefile_user` and `casefile`, or change them together with `DATABASE_URL` in `.env` |
| `POSTGRES_PASSWORD` | A generated password (`openssl rand -hex 16`) |
| `LANGFUSE_DB_PASSWORD` | Another generated password, for Langfuse's own `langfuse` role and database |

In `docker/langfuse/langfuse.env`, replace every `CHANGEME`:

| Variable | Value |
|---|---|
| `NEXTAUTH_SECRET`, `SALT` | Generated secrets (`openssl rand -hex 32`) |
| `ENCRYPTION_KEY` | Exactly 64 hex characters (`openssl rand -hex 32`) |
| `DATABASE_URL` | `postgresql://langfuse:<LANGFUSE_DB_PASSWORD>@postgres:5432/langfuse` |
| `CLICKHOUSE_PASSWORD`, `REDIS_AUTH` | Generated passwords |
| `LANGFUSE_INIT_PROJECT_PUBLIC_KEY`, `LANGFUSE_INIT_PROJECT_SECRET_KEY` | Keys of your choosing, `pk-lf-<random>` and `sk-lf-<random>`; the backend uses them to send traces |
| `LANGFUSE_INIT_USER_PASSWORD` | The password you'll log in to the Langfuse UI with, as `LANGFUSE_INIT_USER_EMAIL` |

The S3 settings already point at the Terraform bucket `local-infra-local-langfuse` in Floci. The `LANGFUSE_INIT_*` values only take effect on Langfuse's first start; after that, change them in the Langfuse UI.

### 2. Postgres and Langfuse

```bash
docker compose up -d --wait
```

This starts Postgres 17 with pgvector on `:5432`, and Langfuse (web, worker, ClickHouse and Redis) with its UI on http://localhost:3001. On an empty data directory Postgres runs `docker/postgres/init.sql` (enables `vector`) and `docker/postgres/init-langfuse.sh` (creates Langfuse's role and database). The data lives in `docker/postgres_data`, `docker/clickhouse_data` and `docker/redis_data`.

On the very first start, `langfuse-worker` can log `min_version does not exist` while the web container is still migrating. Restart it once: `docker compose restart langfuse-worker`.

### 3. Backend settings

```bash
cp .env.example .env
```

Fill in `.env`:

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://casefile_user:<POSTGRES_PASSWORD>@localhost:5432/casefile` |
| `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID` | The Terraform outputs `cognito_user_pool_id` and `cognito_web_client_id` |
| `COGNITO_ISSUER` | `http://localhost:4566/<pool id>` (Floci's issuer) |
| `COGNITO_JWKS_URL` | `http://localhost.floci.io:4566/<pool id>/.well-known/jwks.json` |
| `S3_BUCKET`, `SQS_QUEUE_URL` | The Terraform outputs `backend_bucket_name` and `uploads_queue_url` |
| `LLM_MODEL`, `EMBEDDING_MODEL` | The model ids exactly as LM Studio lists them |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | The `LANGFUSE_INIT_PROJECT_*` keys from `langfuse.env`; leave empty to turn tracing off |

The other values in the template are working defaults for this setup. The table under [Configuration](#configuration) lists the ones you might tune.

### 4. Python environment

```bash
conda create -n rag-backend python=3.13
conda activate rag-backend
pip install -r requirements.txt
alembic upgrade head
```

### 5. API and worker

```bash
fastapi dev main.py                # API on http://127.0.0.1:8000, reloads on changes
```

In a second terminal, with the same env active:

```bash
python -m app.worker               # takes indexing jobs from SQS
```

Without the worker, uploads stay `processing`. You can run more than one worker; each takes one document at a time. Stop a worker with Ctrl+C: it finishes the current document first, and a second Ctrl+C stops it at once.

The first indexing run downloads Docling's layout and table models and the chunk tokenizer (about 500 MB) into `.cache/`.

Check that everything is reachable: `curl http://127.0.0.1:8000/health`.

### Troubleshooting

- Chat returns 500, or documents end up `failed`: LM Studio isn't serving, or a model id in `.env` doesn't match `/v1/models`. Indexing retries 5 times with back-off before failing.
- Every request returns 401: the Cognito ids or the issuer in `.env` don't match the pool that issued the frontend's token.
- Uploads stay `processing`: the worker isn't running, or `SQS_QUEUE_URL` points at the wrong queue.
- Re-index failed or outdated documents with `python -m app.reindex`.

## Commands

```bash
pytest                                       # unit tests, no database or model server needed
python -m app.search "question" [--full]     # retrieval only: hits, scores, sections picked
python -m app.reindex [--all]                # re-queue outdated or failed documents
alembic revision --autogenerate -m "..."     # migration after changing app/models.py
```

## Configuration

Settings come from environment variables or `.env` (`app/config.py`, template in `.env.example`). The main ones:

| Variable | What |
|---|---|
| `DATABASE_URL` | Postgres connection |
| `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, `COGNITO_ISSUER`, `COGNITO_JWKS_URL` | Token verification |
| `AWS_ENDPOINT_URL`, `S3_BUCKET`, `SQS_QUEUE_URL` | Floci locally; unset the endpoint and keys for real AWS |
| `LMSTUDIO_BASE_URL`, `LLM_MODEL`, `EMBEDDING_MODEL` | Model server and model ids |
| `RETRIEVAL_TOP_K`, `RETRIEVAL_MIN_SIMILARITY`, `RETRIEVAL_TOKEN_BUDGET` | Retrieval tuning |
| `OCR_ENGINE` | `ocrmac` (macOS), `auto` or `none` |
| `INDEX_TIMEOUT_SECONDS`, `PARSE_PAGE_BATCH`, `MAX_PAGES` | Worker limits |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | Tracing; it's off when they are unset |
