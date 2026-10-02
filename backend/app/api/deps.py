from __future__ import annotations

from fastapi import HTTPException, UploadFile, status

from app.core.config import get_settings


async def read_upload(file: UploadFile) -> bytes:
    """Read an upload fully while enforcing MAX_UPLOAD_MB."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    chunks, size = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"file exceeds {limit // (1024 * 1024)} MB")
        chunks.append(chunk)
    return b"".join(chunks)
