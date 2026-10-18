"""Service configuration from environment variables (the annotation setup itself is pushed by the training system)."""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_ACCESS_TOKEN_LENGTH = 16


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", protected_namespaces=())

    # Shared secret for every API call (header "X-Access-Key", "Authorization: Bearer <token>" or the login cookie).
    # Empty or too short: the API refuses all requests.
    access_token: str = Field("", alias="CLIENT_ACCESS_TOKEN")
    # Images, thumbnails, SQLite database and the pushed configuration (Docker volume)
    data_dir: str = Field("/data", alias="DATA_DIR")
    # built web UI (client.html + assets/); missing: API only
    static_dir: str = Field("/srv/client-annotator/static", alias="STATIC_DIR")
    max_upload_mb: int = Field(50, alias="MAX_UPLOAD_MB")
    # Optional HTTP(S) proxy for the batch download, e.g. http://proxy-host:8888
    download_proxy: Optional[str] = Field(None, alias="DOWNLOAD_PROXY")
    # Confidence for checks against the inference server; set: overrides the value pushed by the training system
    check_confidence: Optional[float] = Field(None, alias="CHECK_CONFIDENCE", gt=0, le=1)
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @field_validator("check_confidence", mode="before")
    @classmethod
    def _empty_is_unset(cls, v):
        # docker compose passes an unset variable as ""
        return None if isinstance(v, str) and not v.strip() else v

    @property
    def token_valid(self) -> bool:
        return len(self.access_token) >= MIN_ACCESS_TOKEN_LENGTH


@lru_cache
def get_settings() -> Settings:
    return Settings()
