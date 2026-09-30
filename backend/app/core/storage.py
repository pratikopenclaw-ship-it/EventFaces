"""S3-compatible object storage (SeaweedFS locally, R2/S3 in production).

Objects are private; the browser never receives storage URLs for reading.
"""

import time
from collections.abc import Iterator
from datetime import datetime
from functools import lru_cache

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings


# Bounded: a hung storage endpoint must not pin API threads (boto's default is 60 s x 5 tries).
_CONFIG = Config(
    signature_version="s3v4",
    s3={"addressing_style": "path"},
    connect_timeout=5,
    read_timeout=30,
    retries={"mode": "standard", "max_attempts": 3},
)


@lru_cache
def get_s3() -> BaseClient:
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        region_name=s.s3_region,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        config=_CONFIG,
    )


@lru_cache
def get_public_s3() -> BaseClient:
    """Client for presigning URLs the *browser* uses (public endpoint, e.g. localhost:8333
    locally or the R2/S3 hostname in production). Presigned URLs embed the host."""
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_public_endpoint_url or s.s3_endpoint_url,
        region_name=s.s3_region,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        config=_CONFIG,
    )


def presigned_put(key: str, content_type: str, size: int, expires: int) -> str:
    """A URL allowing exactly one object of exactly `size` bytes and `content_type`.

    Content-Type and Content-Length are part of the signature, so the storage server
    rejects any other size or type (verified against SeaweedFS; S3/R2 behave the same).
    """
    return get_public_s3().generate_presigned_url(
        "put_object",
        Params={"Bucket": get_settings().s3_bucket, "Key": key, "ContentType": content_type, "ContentLength": size},
        ExpiresIn=expires,
    )


def head_size(key: str) -> int | None:
    try:
        return int(get_s3().head_object(Bucket=get_settings().s3_bucket, Key=key)["ContentLength"])
    except ClientError:
        return None


def get_range(key: str, start: int, end: int) -> bytes:
    obj = get_s3().get_object(Bucket=get_settings().s3_bucket, Key=key, Range=f"bytes={start}-{end}")
    return obj["Body"].read()


def delete_keys(*keys: str | None) -> None:
    objects = [{"Key": k} for k in keys if k]
    for i in range(0, len(objects), 1000):  # S3 DeleteObjects takes at most 1000 keys
        get_s3().delete_objects(
            Bucket=get_settings().s3_bucket, Delete={"Objects": objects[i : i + 1000], "Quiet": True}
        )


def configure_cors(origins: list[str]) -> None:
    """Allow browsers on our origin to PUT guest uploads straight to the bucket."""
    get_s3().put_bucket_cors(
        Bucket=get_settings().s3_bucket,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedOrigins": origins,
                    "AllowedMethods": ["PUT"],
                    "AllowedHeaders": ["content-type"],
                    "MaxAgeSeconds": 3600,
                }
            ]
        },
    )


def ensure_bucket(retries: int = 20, delay: float = 1.5) -> None:
    bucket = get_settings().s3_bucket
    s3 = get_s3()
    for attempt in range(retries):
        try:
            s3.head_bucket(Bucket=bucket)
            return
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchBucket"):
                s3.create_bucket(Bucket=bucket)
                return
            if attempt == retries - 1:
                raise
        except BotoCoreError:
            if attempt == retries - 1:
                raise
        time.sleep(delay)


def upload_key(event_id: object, photo_id: object) -> str:
    return f"{uploads_prefix(event_id)}{photo_id}"


def photo_key(event_id: object, photo_id: object, variant: str) -> str:
    """Object layout: events/<event>/photos/<photo>/<variant>.jpg (prefix-deletable per event)."""
    return f"events/{event_id}/photos/{photo_id}/{variant}.jpg"


def event_prefix(event_id: object) -> str:
    return f"events/{event_id}/"


def put_jpeg(key: str, data: bytes) -> None:
    get_s3().put_object(Bucket=get_settings().s3_bucket, Key=key, Body=data, ContentType="image/jpeg")


def get_bytes(key: str) -> bytes:
    obj = get_s3().get_object(Bucket=get_settings().s3_bucket, Key=key)
    return obj["Body"].read()


def open_stream(key: str):
    """Streaming body for proxying an object to the client (never expose its URL)."""
    obj = get_s3().get_object(Bucket=get_settings().s3_bucket, Key=key)
    return obj["Body"], obj.get("ContentLength")


def list_objects(prefix: str) -> Iterator[tuple[str, datetime]]:
    """(key, last_modified) for every object under a prefix."""
    paginator = get_s3().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=get_settings().s3_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj["Key"], obj["LastModified"]


def uploads_prefix(event_id: object) -> str:
    return f"events/{event_id}/uploads/"


def delete_prefix(prefix: str) -> int:
    """Delete every object under a prefix. Returns the number of objects deleted."""
    s3 = get_s3()
    bucket = get_settings().s3_bucket
    deleted = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": keys, "Quiet": True})
            deleted += len(keys)
    return deleted
