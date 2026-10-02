from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from odcore.storage import ObjectStorage

from .config import get_settings


@lru_cache
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=3, max_overflow=2)
    return sessionmaker(bind=engine, expire_on_commit=False)


@lru_cache
def storage() -> ObjectStorage:
    return ObjectStorage(get_settings().s3)
