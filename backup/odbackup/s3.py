"""Streaming access to the three S3 buckets (works with Garage or any other S3-compatible store)."""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import BinaryIO, Iterator, Optional

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError

# logical name in the backup -> environment variable with the bucket name (and its default)
BUCKETS = {
    "images": ("S3_BUCKET_IMAGES", "training-images"),
    "datasets": ("S3_BUCKET_DATASETS", "datasets"),
    "models": ("S3_BUCKET_MODELS", "models"),
}
SMALL_OBJECT = 64 * 1024 * 1024  # uploaded in one request; larger objects as multipart stream


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int


@dataclass
class ObjectStream:
    body: BinaryIO
    size: int
    content_type: Optional[str]
    mtime: float


class NotFound(LookupError):
    pass


class SequentialReader(io.RawIOBase):
    """Exposes a stream (e.g. a member of a tar read in stream mode) as explicitly non-seekable.

    boto3 asks file objects whether they are seekable; the tar stream cannot answer that and
    raises. Non-seekable input is uploaded chunk by chunk.
    """

    def __init__(self, stream: BinaryIO):
        self._stream = stream

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def readinto(self, buffer) -> int:
        data = self._stream.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


class S3:
    def __init__(self, client=None, buckets: Optional[dict[str, str]] = None):
        self.client = client or boto3.client(
            "s3",
            endpoint_url=os.environ["S3_ENDPOINT_URL"],
            region_name=os.environ.get("S3_REGION", "garage"),
            aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                          retries={"max_attempts": 10, "mode": "standard"}),
        )
        self.buckets = buckets or {name: os.environ.get(env, default) for name, (env, default) in BUCKETS.items()}
        self._transfer = TransferConfig(multipart_threshold=SMALL_OBJECT, multipart_chunksize=SMALL_OBJECT, use_threads=False)

    def list(self, logical: str) -> list[ObjectInfo]:
        paginator = self.client.get_paginator("list_objects_v2")
        return [ObjectInfo(o["Key"], int(o["Size"]))
                for page in paginator.paginate(Bucket=self.buckets[logical]) for o in page.get("Contents", [])]

    def open(self, logical: str, key: str) -> ObjectStream:
        try:
            obj = self.client.get_object(Bucket=self.buckets[logical], Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                raise NotFound(key) from exc
            raise
        return ObjectStream(obj["Body"], int(obj["ContentLength"]), obj.get("ContentType"), obj["LastModified"].timestamp())

    def put(self, logical: str, key: str, stream: BinaryIO, size: int, content_type: Optional[str]) -> None:
        bucket = self.buckets[logical]
        extra = {"ContentType": content_type} if content_type else {}
        if size <= SMALL_OBJECT:
            self.client.put_object(Bucket=bucket, Key=key, Body=stream.read(), **extra)
        else:  # the tar stream is not seekable: upload it chunk by chunk
            reader = io.BufferedReader(SequentialReader(stream), buffer_size=1024 * 1024)
            self.client.upload_fileobj(reader, bucket, key, ExtraArgs=extra or None, Config=self._transfer)

    def empty(self, logical: str) -> int:
        bucket, removed = self.buckets[logical], 0
        keys = [o.key for o in self.list(logical)]
        for i in range(0, len(keys), 1000):
            batch = keys[i:i + 1000]
            self.client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True})
            removed += len(batch)
        return removed

    def iter_logical(self) -> Iterator[str]:
        yield from BUCKETS
