"""Original-file storage in S3 (Floci locally). New keys are
`uploads/<owner>/<document id><ext>` (`S3_UPLOAD_PREFIX`; objects created there
trigger indexing through EventBridge and SQS); documents uploaded before that
keep their `<owner>/<document id><ext>` key, stored in `documents.storage_key`.
The per-owner part is what IAM prefix conditions will scope later."""

from functools import lru_cache
from typing import BinaryIO

import boto3
from botocore.config import Config

from app.config import get_settings


@lru_cache
def _client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.aws_endpoint_url,
        region_name=settings.aws_default_region,
        # None falls back to boto3's normal credential chain (env, profile, IAM role).
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        config=Config(
            # SigV4 for presigned URLs too (boto3 can fall back to SigV2, which S3
            # rejects for newer regions and Floci treats as an anonymous request).
            signature_version="s3v4",
            # Emulators serve buckets at <endpoint>/<bucket>, not <bucket>.<endpoint>.
            s3={"addressing_style": "path"} if settings.aws_endpoint_url else {},
        ),
    )


def save_file(key: str, file: BinaryIO, content_type: str) -> None:
    """Streams from a file object; large files go up as a multipart upload."""
    _client().upload_fileobj(file, get_settings().s3_bucket, key, ExtraArgs={"ContentType": content_type})


def presigned_get_url(key: str, content_type: str, content_disposition: str, expires_in: int) -> str:
    """A time-limited GET link the browser can open directly. The response headers
    are overridden so the file opens inline (or downloads) under its original name."""
    return _client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": get_settings().s3_bucket,
            "Key": key,
            "ResponseContentType": content_type,
            "ResponseContentDisposition": content_disposition,
        },
        ExpiresIn=expires_in,
    )


def load(key: str) -> bytes:
    return _client().get_object(Bucket=get_settings().s3_bucket, Key=key)["Body"].read()


def delete(key: str) -> None:
    _client().delete_object(Bucket=get_settings().s3_bucket, Key=key)
