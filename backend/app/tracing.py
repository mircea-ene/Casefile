"""Langfuse tracing: one trace per chat request, indexing run and title generation,
tagged with the owner (user_id) and the conversation (session_id).

Model calls go through Langfuse's OpenAI wrapper (`app/ai.py`), which records each
LLM and embedding call with its token usage as a child of the current trace. The
SDK is configured from the environment (`app/__init__.py`); with tracing off every
call here is a no-op. Spans are exported in a background thread, so a down
Langfuse server never fails a request."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langfuse import get_client, propagate_attributes


@contextmanager
def trace(
    name: str,
    *,
    user_id: str,
    session_id: str | None = None,
    input: Any = None,
    metadata: dict[str, str] | None = None,
) -> Iterator[Any]:
    """Starts a trace (its root span). Everything traced inside, including the
    model calls, belongs to it and carries `user_id` / `session_id`."""
    with get_client().start_as_current_observation(name=name, as_type="chain", input=input) as root:
        with propagate_attributes(user_id=user_id, session_id=session_id, metadata=metadata, trace_name=name):
            yield root


def span(name: str, *, as_type: str = "span", input: Any = None):
    """A step inside the current trace (parsing, retrieval, ...)."""
    return get_client().start_as_current_observation(name=name, as_type=as_type, input=input)


def score(name: str, value: float | bool) -> None:
    """A metric on the current trace, for filtering and dashboards in Langfuse."""
    if isinstance(value, bool):
        get_client().score_current_trace(name=name, value=float(value), data_type="BOOLEAN")
    else:
        get_client().score_current_trace(name=name, value=value, data_type="NUMERIC")


def shutdown() -> None:
    """Flushes pending spans; the SDK also does this at interpreter exit."""
    get_client().shutdown()
