from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml
from sqlalchemy import and_, select, func, cast, Integer

from .db import Event, session_scope


_EVENTS_PATH = Path(os.getenv("EVENTS_REGISTRY", "analytics/events.yml")).resolve()


class EventRegistry:
    def __init__(self, path: Path):
        self._path = path
        self._loaded_at: Optional[datetime] = None
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _load(self) -> None:
        with open(self._path, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        events = doc.get("events", {})
        self._cache = events
        self._loaded_at = datetime.now(timezone.utc)

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        if not self._loaded_at:
            self._load()
        return self._cache.get(name)

    def validate(
        self, *, name: str, props: Dict[str, Any], top_level: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        spec = self.get(name)
        if not spec:
            return False, "unknown_event", {}
        required = spec.get("required", [])
        properties = spec.get("properties", {})
        validated: Dict[str, Any] = {}
        extra: Dict[str, Any] = {}
        for key, value in props.items():
            if key in properties:
                validated[key] = value
            else:
                extra[key] = value
        # Consider top-level fields as satisfying requirements too
        present_keys = set(validated.keys())
        if top_level:
            present_keys |= set(top_level.keys())
        missing = [k for k in required if k not in present_keys]
        if missing:
            return False, f"missing_required: {','.join(missing)}", {}
        if extra:
            validated["props_extra"] = extra
        return True, None, validated


registry = EventRegistry(_EVENTS_PATH)


def track_event(*, name: str, session_id: str, user_id: Optional[str], props: Dict[str, Any]) -> int:
    ok, err, cleaned = registry.validate(
        name=name, props=props, top_level={"session_id": session_id, "user_id": user_id}
    )
    if not ok:
        raise ValueError(err or "invalid_event")
    with session_scope() as s:
        ev = Event(name=name, session_id=session_id, user_id=user_id, props=cleaned)
        s.add(ev)
        s.flush()
        return int(ev.id)


def canary_guardrails_ok(
    *, lookback_minutes: int = 60, p95_turn_latency_budget_ms: int = 1500, error_rate_budget: float = 0.05
) -> bool:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=lookback_minutes)
    with session_scope() as s:
        # p95 turn latency from 'turn' event total_turn_latency_ms
        p95_ok = True
        p95_value: Optional[int] = None
        dialect = getattr(getattr(s.bind, "dialect", None), "name", "sqlite")
        if dialect == "postgresql":
            # Use percentile_cont over JSON field casted to int
            json_val = cast((Event.props["total_turn_latency_ms"].astext), Integer)  # type: ignore[attr-defined]
            p95_expr = func.percentile_cont(0.95).within_group(json_val)
            p95_value = s.scalar(
                select(p95_expr).where(and_(Event.name == "turn", Event.ts >= window_start))  # type: ignore[arg-type]
            )
            if p95_value is not None:
                p95_ok = int(p95_value) <= p95_turn_latency_budget_ms
        else:
            q = select(Event).where(
                and_(Event.name == "turn", Event.ts >= window_start)  # type: ignore[arg-type]
            )
            turns = s.scalars(q).all()
            latencies = [int(ev.props.get("total_turn_latency_ms", 0)) for ev in turns]
            if latencies:
                latencies.sort()
                p95_idx = max(int(len(latencies) * 0.95) - 1, 0)
                p95_value = latencies[p95_idx]
                p95_ok = int(p95_value) <= p95_turn_latency_budget_ms

        # error rate via events with name ending with .error
        q_err = select(Event).where(and_(Event.ts >= window_start))  # type: ignore[arg-type]
        evs = s.scalars(q_err).all()
        total = len(evs)
        errors = sum(1 for e in evs if e.name.endswith(".error"))
        err_rate_ok = True if total == 0 else (errors / total) <= error_rate_budget
        return p95_ok and err_rate_ok


