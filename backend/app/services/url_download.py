"""Download training images from HTTP(S) URLs (batch download in the annotation view)."""
from __future__ import annotations

import posixpath
from urllib.parse import unquote, urlsplit

import httpx

from app.core.config import get_settings

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "od-api/0.1 (training image download)"


class DownloadError(Exception):
    pass


def filename_from_url(url: str) -> str:
    name = posixpath.basename(unquote(urlsplit(url).path))
    return name or urlsplit(url).hostname or url


def download_image(url: str) -> bytes:
    """Fetch ``url`` while enforcing MAX_UPLOAD_MB. Raises ``DownloadError``.

    The content is validated afterwards like a regular upload (``decode_upload``).
    """
    if urlsplit(url).scheme not in ("http", "https"):
        raise DownloadError("only http(s) URLs are supported")
    limit = get_settings().max_upload_mb * 1024 * 1024
    try:
        with httpx.stream("GET", url, timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as res:
            if res.status_code >= 400:
                raise DownloadError(f"HTTP {res.status_code}")
            if int(res.headers.get("content-length") or 0) > limit:
                raise DownloadError(f"file exceeds {limit // (1024 * 1024)} MB")
            chunks, size = [], 0
            for chunk in res.iter_bytes(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise DownloadError(f"file exceeds {limit // (1024 * 1024)} MB")
                chunks.append(chunk)
    except httpx.InvalidURL as exc:
        raise DownloadError(f"invalid URL: {exc}") from exc
    except httpx.HTTPError as exc:
        raise DownloadError(f"download failed: {exc.__class__.__name__}: {exc}") from exc
    return b"".join(chunks)
