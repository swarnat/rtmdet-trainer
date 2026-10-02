"""Thin wrapper around boto3 for the Garage S3 storage."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import BinaryIO, Iterator

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class S3Settings:
    endpoint_url: str
    region: str
    access_key_id: str
    secret_access_key: str
    bucket_images: str
    bucket_datasets: str
    bucket_models: str

    @classmethod
    def from_env(cls) -> "S3Settings":
        def req(name: str) -> str:
            value = os.environ.get(name)
            if not value:
                raise RuntimeError(f"environment variable {name} is required")
            return value

        return cls(
            endpoint_url=req("S3_ENDPOINT_URL"),
            region=os.environ.get("S3_REGION", "garage"),
            access_key_id=req("S3_ACCESS_KEY_ID"),
            secret_access_key=req("S3_SECRET_ACCESS_KEY"),
            bucket_images=os.environ.get("S3_BUCKET_IMAGES", "training-images"),
            bucket_datasets=os.environ.get("S3_BUCKET_DATASETS", "datasets"),
            bucket_models=os.environ.get("S3_BUCKET_MODELS", "models"),
        )


class ObjectStorage:
    def __init__(self, settings: S3Settings):
        self.settings = settings
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint_url,
            region_name=settings.region,
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.secret_access_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 5, "mode": "standard"},
            ),
        )

    # -- basic operations -------------------------------------------------
    def put_bytes(self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

    def get_bytes(self, bucket: str, key: str) -> bytes:
        return self.client.get_object(Bucket=bucket, Key=key)["Body"].read()

    def open_stream(self, bucket: str, key: str) -> tuple[BinaryIO, dict]:
        obj = self.client.get_object(Bucket=bucket, Key=key)
        return obj["Body"], {"content_type": obj.get("ContentType"), "content_length": obj.get("ContentLength")}

    def upload_file(self, bucket: str, key: str, path: str, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else None
        self.client.upload_file(path, bucket, key, ExtraArgs=extra)

    def download_file(self, bucket: str, key: str, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.client.download_file(bucket, key, path)

    def exists(self, bucket: str, key: str) -> bool:
        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def copy(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> None:
        self.client.copy_object(Bucket=dst_bucket, Key=dst_key, CopySource={"Bucket": src_bucket, "Key": src_key})

    def delete(self, bucket: str, key: str) -> None:
        self.client.delete_object(Bucket=bucket, Key=key)

    def list_keys(self, bucket: str, prefix: str) -> Iterator[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                yield item["Key"]

    def delete_prefix(self, bucket: str, prefix: str) -> int:
        count = 0
        for key in list(self.list_keys(bucket, prefix)):
            self.delete(bucket, key)
            count += 1
        return count

    def check_buckets(self) -> None:
        for bucket in (self.settings.bucket_images, self.settings.bucket_datasets, self.settings.bucket_models):
            self.client.head_bucket(Bucket=bucket)
