# Casefile

Ask your contracts. Every answer is cited to the clause.

Casefile answers questions about your contracts. You upload them (PDF, DOCX, DOC, images or plain text), Casefile parses and indexes them clause by clause, and you ask questions in a chat. Each answer cites the passages it relies on. Every citation is checked word for word against the source text, and clicking one opens the original PDF at that spot.

## How it works

Docling extracts headings, paragraphs and tables along with their positions on the page. OCR runs only on regions that have no text layer. The text is then grouped into clauses by their clause numbers rather than cut into fixed-size windows.

Before retrieval, a small LLM call analyzes the question. It finds the contracts the question names, which narrow the search to those documents, and rewrites the question as the clause that would answer it. Retrieval combines vector search (pgvector, HNSW) with BM25, which is computed in SQL, and merges the two rankings with reciprocal rank fusion. BM25 only runs on clause numbers and exact defined terms; on party names it ranked preambles and signature blocks above the clause asked about. A section is sent to the model whole when it has several hits or when its heading or number matches the question. A question like "what are X's obligations" therefore gets every clause of that section.

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

## Evaluation

Retrieval was measured on [CUAD](https://www.atticusprojectai.org/cuad), a set of 510 commercial contracts in which lawyers marked the clauses for 41 categories. The eval uses 40 contracts of 5 to 30 pages from 25 contract types (589 pages in total) and 13 categories asked as plain questions ("Can either party terminate this agreement for convenience?"). That gives 520 questions, 249 of which have an answer in the contract. A question counts as retrieved when a lawyer-marked span ends up in the context sent to the model.

| Setup | Gold clause in context | MRR@8 | Context tokens | Latency |
|---|---|---|---|---|
| Question names its contract, search over all 40 | 0.932 | 0.821 | 2,595 | 6.1 s |
| Question scoped to its contract | 0.928 | 0.842 | 2,214 | 2.4 s |

The analysis model resolves the named contract correctly 94% of the time. Latency was measured locally on LM Studio (Qwen3.5 9B for analysis, Qwen3-Embedding 8B). The 6.1 s average comes mostly from 18 questions on which the analysis model looped until it timed out.

The harness is [`backend/app/evaluate.py`](backend/app/evaluate.py). The questions and the per-question results of every run are in [`backend/eval/`](backend/eval/). CUAD is by The Atticus Project, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

### Compared with the first version

The first version searched the question as typed, with vector search and BM25 on the whole question, fused with RRF.

| Setup | Gold in context, first version | Gold in context, now | MRR@8, first version | MRR@8, now |
|---|---|---|---|---|
| Question names its contract, search over all 40 | 0.667 | **0.932** | 0.215 | **0.821** |
| Question scoped to its contract | **0.968** | 0.928 | 0.818 | **0.842** |

Query analysis now picks the contract a question names and rewrites the question as the clause that would answer it, and BM25 runs only on clause numbers and exact terms. Across contracts this is a large gain: party names no longer pull in the preambles and signature blocks of other contracts. Within one contract it ranks the right clause slightly higher and sends 28% less context, but finds it about four points less often, because the rewrite sometimes drifts from the question.

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

## Technologies

| Area | Used |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS v4, AWS Amplify, react-pdf |
| Backend | Python 3.13, FastAPI, SQLAlchemy, Alembic, Docling |
| Data | Postgres 17 with pgvector |
| AWS | Cognito, S3, EventBridge, SQS, emulated locally by Floci |
| Models | LM Studio with Qwen3 and Qwen3-Embedding (any OpenAI-compatible API) |
| Tooling | Terraform, Docker Compose, Langfuse |

## Limitations

- A verified citation proves that the quoted text exists in the source, not that the answer draws the right conclusion from it. The model can still misread a clause it quotes correctly.
- Answer quality depends on the model. It has been run with a local Qwen3 27B, which can miss nuances that a larger model would catch.
- Each question is answered on its own. The model doesn't see earlier turns, so follow-ups like "and what about the renewal term?" need to be asked in full.
- There is no reranker. A cross-encoder (bge-reranker-v2-m3) was tried and removed, because it ranked the right clause lower than the fused order.
- Query analysis uses a 9B model. It sometimes drifts from the question when rewriting it, and on a few questions it loops until the call times out, so the question is searched as typed.
- Only retrieval has been evaluated. Answer quality on CUAD (correct, partial, incorrect, judged by a second model) hasn't been measured yet.
- Images and figures inside documents are skipped. Text in scanned pages is read by OCR, which defaults to Apple Vision and so only runs on macOS. Elsewhere, set `OCR_ENGINE=auto`.
- Documents and models stay on your machine, but Langfuse stores the full prompts and answers, including contract text. Turn tracing off by leaving the Langfuse keys empty.
- Every query is scoped to the signed-in user, but there are no tenants or row-level security in Postgres yet.
- The AWS side has only been run against Floci, not real AWS.
- Casefile is a personal project, not legal advice, and it hasn't been reviewed for production legal use.
