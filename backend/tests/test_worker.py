import json
import uuid

import pytest

from app import indexing_queue, worker
from app.config import get_settings

DOC = uuid.UUID("5b18948d-796e-4066-ac91-efcd72ecb1b7")


def _s3_event(bucket: str, key: str) -> str:
    return json.dumps(
        {
            "version": "0",
            "source": "aws.s3",
            "detail-type": "Object Created",
            "detail": {"bucket": {"name": bucket}, "object": {"key": key, "size": 123}},
        }
    )


def test_parse_s3_event_for_our_bucket():
    key = f"uploads/owner-1/{DOC}.pdf"
    request = indexing_queue.parse_message(_s3_event(get_settings().s3_bucket, key))
    assert request == indexing_queue.IndexRequest(DOC, storage_key=key)


def test_parse_direct_request():
    assert indexing_queue.parse_message(json.dumps({"document_id": str(DOC)})) == indexing_queue.IndexRequest(DOC)


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        "[]",
        json.dumps({"document_id": "nope"}),
        _s3_event("someone-elses-bucket", f"uploads/o/{DOC}.pdf"),
        _s3_event(get_settings().s3_bucket, "uploads/o/not-a-uuid.pdf"),
        json.dumps({"source": "aws.s3", "detail-type": "Object Deleted", "detail": {}}),
    ],
)
def test_other_messages_are_not_requests(body):
    assert indexing_queue.parse_message(body) is None


@pytest.fixture
def queue_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(indexing_queue, "delete", lambda m: calls.append(("delete",)))
    monkeypatch.setattr(indexing_queue, "set_visibility", lambda m, s: calls.append(("visibility", s)))
    monkeypatch.setattr(worker, "mark_failed", lambda d, e: calls.append(("failed", d)))
    return calls


def _message(receive_count: int) -> dict:
    return {
        "Body": json.dumps({"document_id": str(DOC)}),
        "ReceiptHandle": "r",
        "Attributes": {"ApproximateReceiveCount": str(receive_count)},
    }


def test_finished_job_deletes_the_message(monkeypatch, queue_calls):
    monkeypatch.setattr(worker, "run_job", lambda *a: None)
    worker.handle(_message(1), max_attempts=5)
    assert queue_calls == [("delete",)]


def test_failed_attempt_is_retried_with_backoff(monkeypatch, queue_calls):
    monkeypatch.setattr(worker, "run_job", lambda *a: "error")
    worker.handle(_message(2), max_attempts=5)
    assert queue_calls == [("visibility", 60)]


def test_backoff_is_capped_at_the_visibility_timeout(monkeypatch, queue_calls):
    monkeypatch.setattr(worker, "run_job", lambda *a: "error")
    worker.handle(_message(4), max_attempts=10)
    assert queue_calls == [("visibility", min(240, get_settings().index_visibility_seconds))]


def test_last_attempt_fails_the_document_and_releases_the_message(monkeypatch, queue_calls):
    monkeypatch.setattr(worker, "run_job", lambda *a: "killed by signal 9 (out of memory?)")
    worker.handle(_message(5), max_attempts=5)
    assert queue_calls == [("failed", DOC), ("visibility", 0)]


def test_unrelated_message_is_dropped(monkeypatch, queue_calls):
    monkeypatch.setattr(worker, "run_job", lambda *a: pytest.fail("no job for this message"))
    worker.handle({"Body": "garbage", "ReceiptHandle": "r"}, max_attempts=5)
    assert queue_calls == [("delete",)]
