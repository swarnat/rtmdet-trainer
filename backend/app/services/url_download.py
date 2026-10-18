"""Download training images from HTTP(S) URLs (batch download in the annotation view)."""
from __future__ import annotations

from odcore import download
from odcore.download import DownloadError, filename_from_url  # noqa: F401  (re-exported)

from app.core.config import get_settings


def download_image(url: str) -> bytes:
    """Fetch ``url`` while enforcing MAX_UPLOAD_MB, via DOWNLOAD_PROXY if set. Raises ``DownloadError``."""
    settings = get_settings()
    return download.download_image(url, settings.max_upload_mb, settings.download_proxy)
