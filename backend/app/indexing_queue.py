"""The indexing queue (SQS, Floci locally). Two kinds of messages arrive on it:

- S3 "Object Created" events, which EventBridge sends for every upload under
  `S3_UPLOAD_PREFIX` (rule and queue are managed by Terraform, not here);
- `{"document_id": ...}`, sent directly by `python -m app.reindex`.

Delivery is at least once, so the worker must tolerate duplicates."""

import json
import logging
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePath
from urllib.parse import unquote_plus

import boto3

from app.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class IndexRequest:
    document_id: uuid.UUID
    # The uploaded object's key for S3 events (checked against the document's
    # storage_key); None for direct requests.
    storage_key: str | None = None


@lru_cache
def _client():
    settings = get_settings()
    return boto3.client(
        "sqs",
        endpoint_url=settings.aws_endpoint_url,
        region_name=settings.aws_default_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def send(document_id: uuid.UUID) -> None:
    _client().send_message(
        QueueUrl=get_settings().sqs_queue_url, MessageBody=json.dumps({"document_id": str(document_id)})
    )


def receive(wait_seconds: int = 20) -> dict | None:
    """One message (long poll), or None. One at a time: a job can take minutes."""
    response = _client().receive_message(
        QueueUrl=get_settings().sqs_queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=wait_seconds,
        MessageSystemAttributeNames=["ApproximateReceiveCount"],
    )
    messages = response.get("Messages") or []
    return messages[0] if messages else None


def delete(message: dict) -> None:
    _client().delete_message(QueueUrl=get_settings().sqs_queue_url, ReceiptHandle=message["ReceiptHandle"])


def set_visibility(message: dict, seconds: int) -> None:
    """Hides the message for `seconds` from now (0 makes it visible again)."""
    _client().change_message_visibility(
        QueueUrl=get_settings().sqs_queue_url, ReceiptHandle=message["ReceiptHandle"], VisibilityTimeout=seconds
    )


def receive_count(message: dict) -> int:
    return int(message.get("Attributes", {}).get("ApproximateReceiveCount", 1))


def max_receive_count() -> int:
    """Attempts before SQS moves a message to the dead-letter queue (the redrive policy)."""
    settings = get_settings()
    try:
        attributes = _client().get_queue_attributes(
            QueueUrl=settings.sqs_queue_url, AttributeNames=["RedrivePolicy"]
        )["Attributes"]
        return int(json.loads(attributes["RedrivePolicy"])["maxReceiveCount"])
    except Exception:
        log.warning("Couldn't read the queue's redrive policy; assuming %d attempts", settings.index_max_attempts)
        return settings.index_max_attempts


def parse_message(body: str) -> IndexRequest | None:
    """None for anything that isn't an indexing request for our bucket."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        if "document_id" in payload:
            return IndexRequest(uuid.UUID(str(payload["document_id"])))
        if payload.get("source") == "aws.s3" and payload.get("detail-type") == "Object Created":
            detail = payload["detail"]
            if detail["bucket"]["name"] != get_settings().s3_bucket:
                return None
            # Keys are URL-encoded in S3 notifications; ours are UUIDs and an extension anyway.
            key = unquote_plus(detail["object"]["key"])
            return IndexRequest(uuid.UUID(PurePath(key).stem), storage_key=key)
    except (KeyError, TypeError, ValueError):
        return None
    return None
