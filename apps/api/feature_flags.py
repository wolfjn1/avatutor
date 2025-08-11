from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

from sqlalchemy import select

from .db import FeatureFlag, session_scope


def _bucket_for_user(user_id: Optional[str]) -> int:
    if not user_id:
        return 0
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


@dataclass
class CachedFlag:
    enabled: bool
    rollout_percent: int
    ts: float


class FeatureFlagService:
    def __init__(self, ttl_seconds: int = 5):
        self._cache: Dict[str, CachedFlag] = {}
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def _load(self, name: str) -> Optional[CachedFlag]:
        with session_scope() as s:
            row: Optional[FeatureFlag] = s.scalar(select(FeatureFlag).where(FeatureFlag.name == name))
            if row is None:
                return None
            return CachedFlag(
                enabled=row.enabled, rollout_percent=row.rollout_percent, ts=time.time()
            )

    def is_enabled(self, name: str, user_id: Optional[str] = None) -> bool:
        with self._lock:
            cached = self._cache.get(name)
            now = time.time()
            if not cached or now - cached.ts > self._ttl:
                cached = self._load(name)
                if cached:
                    self._cache[name] = cached
        if not cached:
            return False
        if not cached.enabled:
            return False
        # Sticky percent rollout by user bucket
        bucket = _bucket_for_user(user_id)
        return bucket < cached.rollout_percent if cached.rollout_percent < 100 else True

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()


flags = FeatureFlagService()


