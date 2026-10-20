"""Indexing worker: takes jobs from the SQS queue and indexes the documents.

    python -m app.worker

Run as many as needed (one job at a time each; Docling is memory hungry). Every
job runs in a fresh child process, so a crash or out-of-memory kill on a large
document only fails that attempt, memory is returned after each job, and a job
that hangs is killed after INDEX_TIMEOUT_SECONDS.

Per message:
- not an indexing request (other bucket, garbage): deleted;
- the job is done with (indexed, unsupported content, or nothing to do): deleted;
- the job errored, crashed or timed out: retried after a back-off, until the
  queue's maxReceiveCount; the last attempt marks the document failed and SQS
  moves the message to the dead-letter queue (so a DLQ alarm flags outages).

While a job runs, its message's visibility is extended every
INDEX_HEARTBEAT_SECONDS, so long documents aren't redelivered mid-job. Every few
minutes, documents stuck in processing for INDEX_STALE_AFTER_SECONDS are failed.
SIGTERM / Ctrl+C stops taking new jobs; a second one stops at once."""

import logging
import multiprocessing
import signal
import sys
import time
import uuid

from app import indexing_queue, tracing
from app.config import get_settings
from app.ingestion import IndexResult, fail_stale_indexing, index_document, mark_failed

log = logging.getLogger("app.worker")

SWEEP_INTERVAL_SECONDS = 600
RETRY_BACKOFF_SECONDS = 30  # doubled per attempt, up to INDEX_VISIBILITY_SECONDS
EXIT_RETRY = 1
EXIT_GAVE_UP = 3  # the job already marked the document failed; dead-letter the message

_stopping = False
_current: multiprocessing.Process | None = None  # the running job, killed on a second signal


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    settings = get_settings()
    max_attempts = indexing_queue.max_receive_count()
    log.info("Worker started on %s (%d attempts per document)", settings.sqs_queue_url, max_attempts)

    last_sweep = 0.0
    while not _stopping:
        if time.monotonic() - last_sweep > SWEEP_INTERVAL_SECONDS:
            last_sweep = time.monotonic()
            try:
                if failed := fail_stale_indexing(settings.index_stale_after_seconds):
                    log.warning("Marked %d stale processing document(s) failed", failed)
            except Exception:
                log.exception("Stale-document sweep failed")
        try:
            message = indexing_queue.receive()
        except Exception:
            log.exception("Couldn't receive from the queue; retrying")
            time.sleep(5)
            continue
        if message is None:
            continue
        if _stopping:  # signalled during the long poll: hand the message back untouched
            indexing_queue.set_visibility(message, 0)
            break
        handle(message, max_attempts)
    log.info("Worker stopped")


def _stop(signum, _frame) -> None:
    global _stopping
    if _stopping:
        if _current is not None and _current.is_alive():
            _current.kill()  # its message becomes visible again after the visibility timeout
        sys.exit(1)
    _stopping = True
    log.info("Stopping after the current job (signal again to stop now)")


def handle(message: dict, max_attempts: int) -> None:
    request = indexing_queue.parse_message(message.get("Body", ""))
    if request is None:
        log.warning("Ignoring a message that isn't an indexing request: %.300s", message.get("Body"))
        indexing_queue.delete(message)
        return

    attempt = indexing_queue.receive_count(message)
    final = attempt >= max_attempts
    log.info("Indexing %s (attempt %d/%d)", request.document_id, attempt, max_attempts)
    error = run_job(message, request.document_id, request.storage_key, final)
    if error is None:
        indexing_queue.delete(message)
        return

    if final:
        log.error("Giving up on %s after %d attempts: %s", request.document_id, attempt, error)
        mark_failed(request.document_id, f"Indexing failed after {attempt} attempts: {error}")
        # Visible again at once, so SQS moves it to the dead-letter queue on its next receive.
        indexing_queue.set_visibility(message, 0)
    else:
        delay = min(RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1), get_settings().index_visibility_seconds)
        log.warning("Attempt %d for %s failed (%s); retrying in %d s", attempt, request.document_id, error, delay)
        indexing_queue.set_visibility(message, delay)


def run_job(message: dict, document_id: uuid.UUID, storage_key: str | None, final: bool) -> str | None:
    """Runs the job in a child process, keeping the message hidden meanwhile.
    Returns None when the job finished, else what went wrong."""
    global _current
    settings = get_settings()
    process = multiprocessing.get_context("spawn").Process(
        target=_job, args=(str(document_id), storage_key, final), name=f"index-{document_id}"
    )
    started = time.monotonic()
    process.start()
    _current = process
    try:
        return _supervise(process, message, document_id, started)
    finally:
        _current = None


def _supervise(process: multiprocessing.Process, message: dict, document_id: uuid.UUID, started: float) -> str | None:
    settings = get_settings()
    while True:
        process.join(timeout=settings.index_heartbeat_seconds)
        if not process.is_alive():
            break
        if time.monotonic() - started > settings.index_timeout_seconds:
            process.terminate()
            process.join(timeout=30)
            if process.is_alive():
                process.kill()
                process.join()
            return f"timed out after {settings.index_timeout_seconds} s"
        try:
            indexing_queue.set_visibility(message, settings.index_visibility_seconds)
        except Exception:
            log.warning("Couldn't extend the visibility of %s's message", document_id, exc_info=True)

    if process.exitcode == 0:
        return None
    if process.exitcode == EXIT_GAVE_UP:
        return "gave up on the last attempt (see the log above)"
    if process.exitcode is not None and process.exitcode < 0:
        return f"killed by signal {-process.exitcode} (out of memory?)"
    return f"error (exit code {process.exitcode}; see the log above)"


def _job(document_id: str, storage_key: str | None, final: bool) -> None:
    """Child process entry point. Exits 0 when the job is done with (indexed,
    unsupported, nothing to do), EXIT_RETRY when it should be retried, and
    EXIT_GAVE_UP when the last attempt failed."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Ctrl+C reaches the whole process group; let the parent decide.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    code = 0
    try:
        result = index_document(uuid.UUID(document_id), storage_key=storage_key, final_attempt=final)
        log.info("Document %s: %s", document_id, result)
        if result == IndexResult.GAVE_UP:
            code = EXIT_GAVE_UP
    except Exception:
        log.exception("Indexing %s failed", document_id)
        code = EXIT_RETRY
    finally:
        # Child processes skip atexit handlers, so flush the traces here.
        tracing.shutdown()
    sys.exit(code)


if __name__ == "__main__":
    main()
