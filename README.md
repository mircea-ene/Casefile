# Casefile

Ask your contracts. Every answer is cited to the clause.

Casefile answers questions about your contracts. You upload them (PDF, DOCX, DOC, images or plain text), Casefile parses and indexes them clause by clause, and you ask questions in a chat. Each answer cites the passages it relies on. Every citation is checked word for word against the source text, and clicking one opens the original PDF at that spot.

## How it works

1. **Indexing.** Docling extracts the text with its position on the page (OCR only where there's no text layer). The text is split into clauses by clause number, embedded and stored in Postgres with pgvector.
2. **Question analysis.** An LLM call finds the contract the question names, narrows the search to it, and rewrites the question as the clause that would answer it.
3. **Retrieval.** Vector search, plus BM25 on clause numbers and defined terms, fused with RRF. Sections with several hits are sent whole.
4. **Answer.** The model cites a quote per source. Each quote is checked word for word against the document and dropped if it isn't there; with none left, the answer says there isn't enough evidence. Citations open the original PDF at the cited passage.

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

Tested on 40 contracts from [CUAD](https://www.atticusprojectai.org/cuad) (589 pages, 25 contract types) with 520 questions such as "Can either party terminate for convenience?". Lawyers marked the answering clause for 249 of them. Each question names its contract, and the search runs over all 40.

| | |
|---|---|
| Right clause sent to the model | **93%** |
| Right clause is the top source | **75%** |
| Right contract identified | **94%** |
| Median retrieval time | **2.9 s** |

These numbers come from small local models running in LM Studio: Qwen3.5 9B for question analysis and Qwen3-Embedding 8B (truncated to 1024 dimensions) for embeddings. Larger models, especially for question analysis, should do better.

The first version, which searched the question as typed, sent the right clause 67% of the time. Harness: [`backend/app/evaluate.py`](backend/app/evaluate.py). Questions and per-question results: [`backend/eval/`](backend/eval/). CUAD is by The Atticus Project, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

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
- Query analysis sometimes drifts from the question when rewriting it, which can cost the right clause.
- Only retrieval has been evaluated. Answer quality on CUAD (correct, partial, incorrect, judged by a second model) hasn't been measured yet.
- Images and figures inside documents are skipped. Text in scanned pages is read by OCR, which defaults to Apple Vision and so only runs on macOS. Elsewhere, set `OCR_ENGINE=auto`.
- Documents and models stay on your machine, but Langfuse stores the full prompts and answers, including contract text. Turn tracing off by leaving the Langfuse keys empty.
- Every query is scoped to the signed-in user, but there are no tenants or row-level security in Postgres yet.
- The AWS side has only been run against Floci, not real AWS.
- Casefile is a personal project, not legal advice, and it hasn't been reviewed for production legal use.
