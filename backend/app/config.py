from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://rag:rag@localhost:5432/rag"

    # Comma-separated list of allowed browser origins.
    cors_origins: str = "http://localhost:3000"

    cognito_user_pool_id: str = "us-east-1_63b12053a"
    cognito_client_id: str = "cbf8bd4caba94246900339a1a5"
    cognito_issuer: str = "http://localhost:4566/us-east-1_63b12053a"
    cognito_jwks_url: str = "http://localhost.floci.io:4566/us-east-1_63b12053a/.well-known/jwks.json"

    # S3 for original files. Leave the endpoint unset for real AWS; leave the keys
    # unset to use boto3's default credential chain.
    aws_endpoint_url: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_default_region: str = "us-east-1"
    s3_bucket: str = "local-infra-local-backend"

    # Uploads go under this prefix: an EventBridge rule on "Object Created" there
    # puts a message on the indexing queue (both managed by Terraform).
    s3_upload_prefix: str = "uploads/"

    # Indexing queue (SQS) consumed by `python -m app.worker`. Re-indexing sends to it directly.
    sqs_queue_url: str = "http://localhost:4566/000000000000/local-infra-local-uploads"
    # While a job runs, the worker pushes the message's visibility out to this many
    # seconds every `index_heartbeat_seconds`, so long documents aren't redelivered
    # mid-job and a crashed worker's message comes back within this time.
    index_visibility_seconds: int = 300
    index_heartbeat_seconds: int = 60
    # Hard limit per attempt; the job's process is killed after it.
    index_timeout_seconds: int = 3600
    # Used when the queue's redrive policy can't be read.
    index_max_attempts: int = 5
    # A document still processing after this long is marked failed (its message
    # went to the dead-letter queue, or the worker died on the last attempt).
    index_stale_after_seconds: int = 6 * 3600
    # PDFs are converted this many pages at a time, which bounds Docling's memory.
    parse_page_batch: int = 25
    # Longer documents are rejected (failed) instead of indexed.
    max_pages: int = 1000

    max_upload_bytes: int = 50 * 1024 * 1024
    # Lifetime of the presigned URLs from GET /documents/{id}/file.
    file_url_expires_seconds: int = 300

    # LM Studio's OpenAI-compatible server. Model ids are what LM Studio shows
    # for the loaded models (`lms ls` or GET /v1/models).
    lmstudio_base_url: str = "http://localhost:1234/v1"
    lmstudio_api_key: str = "lm-studio"
    llm_model: str = "qwen/qwen3.8-27b"
    embedding_model: str = "text-embedding-qwen3-embedding-8b"
    # Qwen3-Embedding is Matryoshka-trained, so vectors are truncated to this
    # size and re-normalized. Must match the vector column in the migrations.
    embedding_dimensions: int = 1024
    # Qwen3-Embedding expects an instruction on queries only, not documents.
    embedding_query_instruction: str = (
        "Instruct: Given a question about legal documents, retrieve passages that answer it\nQuery: "
    )

    # Model downloads (Hugging Face hub: Docling layout/table models, the chunk
    # tokenizer; Docling's own artifacts) go under this directory, not ~/.cache.
    cache_dir: Path = PROJECT_ROOT / ".cache"

    # Docling OCR for pages without a text layer: "ocrmac" (Apple Vision, macOS
    # only; falls back to "auto" elsewhere), "auto" (Docling picks an installed
    # engine) or "none".
    ocr_engine: str = "ocrmac"
    # Chunk sizes are in tokens of this tokenizer (the embedding model's).
    chunk_tokenizer: str = "Qwen/Qwen3-Embedding-8B"
    chunk_min_tokens: int = 200
    chunk_max_tokens: int = 800

    retrieval_top_k: int = 8
    # Candidates taken from each of vector and full-text search before fusion.
    retrieval_candidates: int = 40
    # Chunks below this cosine similarity are ignored; if none remain the
    # answer is "insufficient evidence". Tune per embedding model.
    retrieval_min_similarity: float = 0.4
    # Hierarchical retrieval: the top chunk hits and section matches pick sections,
    # which are sent whole (in document order) while they fit this many tokens.
    retrieval_token_budget: int = 6000
    # Section-embedding matches that count towards a section's score.
    retrieval_section_candidates: int = 5
    # Section embeddings see at most this many tokens (LM Studio loads Qwen3-Embedding
    # with a 2048-token context by default and truncates longer input silently).
    section_embed_max_tokens: int = 2000

    # Langfuse tracing (token usage per user / conversation / request). Off unless both
    # keys are set; the local instance runs in docker-compose (keys in docker/langfuse/langfuse.env).
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str = "http://localhost:3001"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
