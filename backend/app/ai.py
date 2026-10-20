"""LLM and embedding calls through LM Studio's OpenAI-compatible API.

Swapping to another OpenAI-compatible server only needs new LMSTUDIO_* /
model settings; Bedrock will need its own implementation of these functions.
Chat calls go through Langfuse's drop-in OpenAI wrapper, which records each one
with its token usage in the current trace (`app/tracing.py`); `name` labels it
there. LM Studio reports 0 tokens for embeddings, so those bypass the wrapper
(plain HTTP: importing it patches every OpenAI client) and are recorded by hand,
counted with the chunk tokenizer (the embedding model's)."""

import json
import logging
import math
from functools import lru_cache

import httpx
from langfuse.openai import OpenAI

from app import tracing
from app.chunking import count_tokens
from app.config import get_settings

log = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 32


@lru_cache
def _client() -> OpenAI:
    settings = get_settings()
    return OpenAI(base_url=settings.lmstudio_base_url, api_key=settings.lmstudio_api_key, timeout=300)


@lru_cache
def _embedding_http() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        base_url=settings.lmstudio_base_url,
        headers={"Authorization": f"Bearer {settings.lmstudio_api_key}"},
        timeout=300,
    )


def _truncate_and_normalize(vector: list[float], dimensions: int) -> list[float]:
    vector = vector[:dimensions]
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def _embed(texts: list[str], name: str) -> list[list[float]]:
    settings = get_settings()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start : start + EMBED_BATCH_SIZE]
        # Not the texts themselves: a document's would be stored in Langfuse a second time.
        with tracing.span(name, as_type="embedding", input={"texts": len(batch)}) as observation:
            response = _embedding_http().post("embeddings", json={"model": settings.embedding_model, "input": batch})
            response.raise_for_status()
            observation.update(model=settings.embedding_model, usage_details={"input": _count_tokens(batch)})
        for item in sorted(response.json()["data"], key=lambda d: d["index"]):
            embedding = item["embedding"]
            if len(embedding) < settings.embedding_dimensions:
                raise ValueError(
                    f"Embedding model returned {len(embedding)} dimensions, "
                    f"expected at least {settings.embedding_dimensions}"
                )
            vectors.append(_truncate_and_normalize(embedding, settings.embedding_dimensions))
    return vectors


def _count_tokens(texts: list[str]) -> int:
    return sum(count_tokens(t) for t in texts)


def embed_documents(texts: list[str]) -> list[list[float]]:
    return _embed(texts, "embed_documents")


def embed_query(text: str) -> list[float]:
    return _embed([get_settings().embedding_query_instruction + text], "embed_query")[0]


def complete_json(system: str, user: str, schema: dict, name: str = "complete_json") -> dict:
    """Chat completion constrained to `schema` (LM Studio structured output)."""
    response = _client().chat.completions.create(
        model=get_settings().llm_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.1,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "response", "strict": True, "schema": schema},
        },
        name=name,
    )
    print(response)
    message = response.choices[0].message
    # Thinking models (Qwen3.x) behind LM Studio's reasoning parser can return the
    # whole structured output as `reasoning_content`, leaving `content` empty.
    raw = message.content or getattr(message, "reasoning_content", None) or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("LLM returned non-JSON output: %.500r", raw)
        return {}
