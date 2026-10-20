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

## Technologies

| Area | Used |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, AWS Amplify (auth), react-pdf, react-markdown |
| Backend | Python 3.13, FastAPI, SQLAlchemy, Alembic, boto3 |
| Documents | Docling (layout, tables, OCR with Apple Vision), pypdf |
| Search | Postgres 17 with pgvector (HNSW), BM25 in SQL, reciprocal rank fusion |
| Models | Any OpenAI-compatible API; locally LM Studio with Qwen3 (chat) and Qwen3-Embedding (embeddings) |
| AWS | Cognito, S3, EventBridge, SQS with a dead-letter queue, IAM; emulated locally by Floci |
| Infrastructure | Terraform, Docker Compose |
| Tracing | Langfuse (self-hosted, with ClickHouse and Redis) |

## Repository

| Path | What |
|---|---|
| `infrastructure/` | Floci (local AWS) and the Terraform that creates Cognito, the S3 buckets, the EventBridge rule and the SQS queues. |
| `backend/` | FastAPI API and indexing worker, with Postgres and Langfuse in Docker Compose. |
| `frontend/` | Next.js app. |

Each folder has its own README with the details of running and configuring it.

## Running locally

You need Docker, Terraform (>= 1.16.5), conda, Node.js and LM Studio. The steps below start everything in order. Each app's README covers its own setup in more detail.

### 1. LM Studio

The backend calls LM Studio for chat and embeddings. Before starting the backend:

- Download an LLM and an embedding model. The defaults in `backend/.env.example` are `qwen/qwen3.8-27b` and `text-embedding-qwen3-embedding-8b`. You can use others, as long as you set their ids in `backend/.env`.
- The LLM must support structured output (JSON schema). Qwen3 models do.
- Give the LLM a context length of at least 16k tokens. A prompt carries up to about 6,000 tokens of sources plus the instructions and the answer.
- Load both models at once, or turn on just-in-time model loading.
- Start the local server (Developer tab, Start Server) on port 1234. `curl http://localhost:1234/v1/models` should list both ids exactly as they appear in `backend/.env`.

The default models need roughly 32 GB of memory together. Smaller models work, with weaker answers.

### 2. Floci

From the repository root:

```bash
cd infrastructure
docker compose up -d --wait        # Floci on :4566, its UI on http://localhost:4500
```

### 3. AWS resources (Terraform)

Terraform already points at Floci and uses its dummy credentials, so it needs no AWS configuration. To inspect the resources with the AWS CLI afterwards, point the CLI at Floci in the same shell:

```bash
export AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
```

Then create the resources:

```bash
cd terraform/local
terraform init
terraform apply
terraform output
```

### 4. Configure the apps

Copy the templates, from the repository root:

```bash
cp backend/.env.example backend/.env
cp backend/docker/postgres/postgres.env.example backend/docker/postgres/postgres.env
cp backend/docker/langfuse/langfuse.env.example backend/docker/langfuse/langfuse.env
cp frontend/.env.example frontend/.env.local
```

Then fill them in:

- Put the Terraform outputs (Cognito pool and client ids, bucket name, queue URL) into `backend/.env` and `frontend/.env.local`. The table in `infrastructure/README.md` shows which output goes where.
- Replace every `CHANGEME` in `postgres.env` and `langfuse.env` with a generated secret (`openssl rand -hex 32`). The Postgres password also goes into `DATABASE_URL` in `backend/.env`, and Langfuse's database password into `DATABASE_URL` in `langfuse.env`.
- Choose the Langfuse project keys in `langfuse.env` (`LANGFUSE_INIT_PROJECT_PUBLIC_KEY=pk-lf-...`, `LANGFUSE_INIT_PROJECT_SECRET_KEY=sk-lf-...`) and copy the same values into `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` in `backend/.env`.

`backend/README.md` describes each setting.

### 5. Backend

From the repository root:

```bash
cd backend
docker compose up -d --wait        # Postgres on :5432, Langfuse on http://localhost:3001
conda create -n rag-backend python=3.13
conda activate rag-backend
pip install -r requirements.txt
alembic upgrade head               # create the database tables
fastapi dev main.py                # API on http://127.0.0.1:8000
```

In a second terminal, from `backend/` with the same conda env, start the indexing worker. Without it, uploaded documents stay in `processing`.

```bash
python -m app.worker
```

The first document you index downloads Docling's models and the tokenizer (about 500 MB) into `backend/.cache/`.

### 6. Frontend

From the repository root:

```bash
cd frontend
npm install
npm run dev                        # http://localhost:3000
```

Open http://localhost:3000 and register. Floci doesn't send emails; the confirmation code is listed at http://localhost.floci.io:4566/_aws/ses.

## Tests

```bash
cd backend && pytest               # no database or model server needed
```
