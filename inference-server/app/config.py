"""Service configuration, exclusively from environment variables."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_ACCESS_KEY_LENGTH = 16


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", protected_namespaces=())

    # Shared secret for model uploads (header "X-Access-Key" or "Authorization: Bearer <key>").
    # Empty or too short: uploads are disabled.
    model_upload_key: str = Field("", alias="MODEL_UPLOAD_KEY")
    # Persistent directory for the active model (Docker volume)
    model_dir: str = Field("/data/models", alias="MODEL_DIR")
    # Lowest confidence a detection may have; also the default threshold of /detect
    min_confidence: float = Field(0.15, alias="MIN_CONFIDENCE", gt=0, le=1)
    openvino_device: str = Field("CPU", alias="OPENVINO_DEVICE")
    max_upload_mb: int = Field(50, alias="MAX_UPLOAD_MB")
    max_model_upload_mb: int = Field(1024, alias="MAX_MODEL_UPLOAD_MB")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @property
    def uploads_enabled(self) -> bool:
        return len(self.model_upload_key) >= MIN_ACCESS_KEY_LENGTH


@lru_cache
def get_settings() -> Settings:
    return Settings()
