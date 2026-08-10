"""Blob storage: local filesystem by default, S3/MinIO when S3_ENDPOINT is set.

Backend never parses document bytes (engines run in the browser); it only
stores and returns opaque blobs keyed by org/doc/version.
"""
import os
from urllib.parse import quote

from .settings import (
    S3_ACCESS_KEY,
    S3_BUCKET,
    S3_ENDPOINT,
    S3_REGION,
    S3_SECRET_KEY,
    STORAGE_DIR,
)

_use_s3 = bool(S3_ENDPOINT)


def content_disposition(title: str) -> str:
    """RFC 6266 Content-Disposition. HTTP headers are latin-1 only, so a title
    with non-ASCII chars (e.g. Chinese seed docs) must go in filename*, with an
    ASCII-safe filename= fallback for simple parsers."""
    ascii_name = title.encode("ascii", "replace").decode("ascii").replace('"', "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(title)}"


def _s3_client():
    import boto3  # lazy: only needed when S3 is configured

    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
    )


def _local_path(key: str) -> str:
    return os.path.join(STORAGE_DIR, key)


def put_blob(key: str, data: bytes) -> None:
    if _use_s3:
        _s3_client().put_object(Bucket=S3_BUCKET, Key=key, Body=data)
        return
    path = _local_path(key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def get_blob(key: str) -> bytes:
    if _use_s3:
        return _s3_client().get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
    with open(_local_path(key), "rb") as f:
        return f.read()
