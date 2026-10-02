"""Service configuration, exclusively from environment variables."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from odcore.storage import S3Settings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", protected_namespaces=())

    database_url: str = Field(..., alias="DATABASE_URL")
    redis_url: str = Field("redis://redis:6379/0", alias="REDIS_URL")
    training_queue: str = Field("training", alias="TRAINING_QUEUE")

    s3_endpoint_url: str = Field(..., alias="S3_ENDPOINT_URL")
    s3_region: str = Field("garage", alias="S3_REGION")
    s3_access_key_id: str = Field(..., alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str = Field(..., alias="S3_SECRET_ACCESS_KEY")
    s3_bucket_images: str = Field("training-images", alias="S3_BUCKET_IMAGES")
    s3_bucket_datasets: str = Field("datasets", alias="S3_BUCKET_DATASETS")
    s3_bucket_models: str = Field("models", alias="S3_BUCKET_MODELS")

    model_cache_dir: str = Field("/var/cache/od-models", alias="MODEL_CACHE_DIR")
    openvino_device: str = Field("CPU", alias="OPENVINO_DEVICE")
    # Max. number of compiled (model version, resolution) pairs kept in memory
    compiled_model_cache_size: int = Field(6, alias="COMPILED_MODEL_CACHE_SIZE")
    max_upload_mb: int = Field(50, alias="MAX_UPLOAD_MB")
    cors_origins: str = Field("", alias="CORS_ORIGINS")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    def s3(self) -> S3Settings:
        return S3Settings(
            endpoint_url=self.s3_endpoint_url,
            region=self.s3_region,
            access_key_id=self.s3_access_key_id,
            secret_access_key=self.s3_secret_access_key,
            bucket_images=self.s3_bucket_images,
            bucket_datasets=self.s3_bucket_datasets,
            bucket_models=self.s3_bucket_models,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
