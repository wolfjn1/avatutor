from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Generator

import redis


_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _client() -> redis.Redis:
    return redis.from_url(_REDIS_URL, decode_responses=True)


@contextmanager
def path_lock(path: str, ttl_seconds: int = 60) -> Generator[bool, None, None]:
    key = f"lock:{path}"
    r = _client()
    acquired = bool(r.set(key, str(time.time()), nx=True, ex=ttl_seconds))
    try:
        yield acquired
    finally:
        if acquired:
            try:
                r.delete(key)
            except Exception:
                pass


