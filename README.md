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
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS v4, AWS Amplify, react-pdf |
| Backend | Python 3.13, FastAPI, SQLAlchemy, Alembic, Docling |
| Data | Postgres 17 with pgvector |
| AWS | Cognito, S3, EventBridge, SQS, emulated locally by Floci |
| Models | LM Studio with Qwen3 and Qwen3-Embedding (any OpenAI-compatible API) |
| Tooling | Terraform, Docker Compose, Langfuse |

## Running locally

You need Docker, Terraform (>= 1.16.5), conda, Node.js and LM Studio. Each step links to the README with the details. All paths are from the repository root.

1. **LM Studio.** Load an LLM with structured output support and at least 16k context, plus an embedding model (defaults: `qwen/qwen3.8-27b` and `text-embedding-qwen3-embedding-8b`, roughly 32 GB of memory together). Start the server on port 1234 and check that `curl localhost:1234/v1/models` lists both ids.

2. **Floci and the AWS resources** ([infrastructure/README.md](infrastructure/README.md)). Terraform already targets Floci; the `export` is only for the AWS CLI.

   ```bash
   cd infrastructure && docker compose up -d --wait
   export AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
   cd terraform/local && terraform init && terraform apply
   ```

3. **Configuration.** Copy the templates, put the `terraform output` values into `backend/.env` and `frontend/.env.local`, and replace each `CHANGEME` with a generated secret. The app READMEs list every value.

   ```bash
   cp backend/.env.example backend/.env
   cp backend/docker/postgres/postgres.env.example backend/docker/postgres/postgres.env
   cp backend/docker/langfuse/langfuse.env.example backend/docker/langfuse/langfuse.env
   cp frontend/.env.example frontend/.env.local
   ```

4. **Backend** ([backend/README.md](backend/README.md)). Start the worker in a second terminal, or uploads stay `processing`.

   ```bash
   cd backend && docker compose up -d --wait     # Postgres, Langfuse on :3001
   conda create -n rag-backend python=3.13 && conda activate rag-backend
   pip install -r requirements.txt
   alembic upgrade head
   fastapi dev main.py                           # API on :8000
   python -m app.worker                          # second terminal
   ```

5. **Frontend** ([frontend/README.md](frontend/README.md)).

   ```bash
   cd frontend && npm install && npm run dev     # http://localhost:3000
   ```

   Register, then take the confirmation code from http://localhost.floci.io:4566/_aws/ses (Floci doesn't send emails).
