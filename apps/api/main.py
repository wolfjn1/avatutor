from __future__ import annotations

import os
from typing import Any, Dict, Optional

import structlog
from fastapi import Depends, FastAPI, HTTPException, WebSocket
from fastapi.responses import JSONResponse

from .celery_app import celery_app  # noqa: F401  # ensure celery is importable
from .db import Event, FeatureFlag, init_db, session_scope, upsert_flag
from .feature_flags import flags
from .schemas import FlagCreate, FlagOut, FlagUpdate, TelemetryEventIn, TelemetryEventOut
from .experiments import load_experiment
from .telemetry import track_event
from .ws_audio import handle_audio_ws
from .tasks.cto_review import cto_review
from .tasks.reviews import head_design, head_product, head_engineering, auto_merge_if_safe


logger = structlog.get_logger(__name__)

app = FastAPI(title="AI Tutor Autopilot API", version=os.getenv("APP_VERSION", "0.1.0"))


@app.on_event("startup")
def on_startup() -> None:
    # Ensure DB schema is migrated at app start (idempotent)
    init_db()


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "build": app.version,
    }


@app.get("/flags")
def list_flags() -> Dict[str, Any]:
    with session_scope() as s:
        rows = s.query(FeatureFlag).all()
        out = [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "enabled": r.enabled,
                "rollout_percent": r.rollout_percent,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    return {"flags": out}


@app.get("/flags/{name}", response_model=FlagOut)
def get_flag(name: str) -> FlagOut:
    with session_scope() as s:
        row = s.query(FeatureFlag).filter(FeatureFlag.name == name).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        return FlagOut(
            id=row.id,
            name=row.name,
            description=row.description,
            enabled=row.enabled,
            rollout_percent=row.rollout_percent,
            created_by=row.created_by,
            created_at=row.created_at,
        )


@app.post("/flags")
def set_flag(payload: FlagCreate | FlagUpdate) -> Dict[str, Any]:
    name: Optional[str] = getattr(payload, "name", None)
    if name is None:
        raise HTTPException(status_code=400, detail="name required")
    with session_scope() as s:
        if isinstance(payload, FlagCreate):
            upsert_flag(
                session=s,
                name=name,
                description=payload.description,
                enabled=payload.enabled,
                rollout_percent=payload.rollout_percent,
                created_by=payload.created_by,
            )
        else:
            upsert_flag(
                session=s,
                name=name,
                enabled=payload.enabled,
                rollout_percent=payload.rollout_percent,
            )
    flags.clear_cache()
    return {"ok": True}


@app.put("/flags/{name}", response_model=FlagOut)
def update_flag(name: str, payload: FlagUpdate) -> FlagOut:
    with session_scope() as s:
        row = s.query(FeatureFlag).filter(FeatureFlag.name == name).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        if payload.enabled is not None:
            row.enabled = payload.enabled
        if payload.rollout_percent is not None:
            row.rollout_percent = payload.rollout_percent
        s.flush()
        result = FlagOut(
            id=row.id,
            name=row.name,
            description=row.description,
            enabled=row.enabled,
            rollout_percent=row.rollout_percent,
            created_by=row.created_by,
            created_at=row.created_at,
        )
    flags.clear_cache()
    return result


@app.post("/telemetry/track", response_model=TelemetryEventOut)
def telemetry_track(ev: TelemetryEventIn) -> TelemetryEventOut:
    try:
        event_id = track_event(
            name=ev.name, session_id=ev.session_id, user_id=ev.user_id, props=ev.props
        )
    except ValueError as e:  # invalid event
        raise HTTPException(status_code=400, detail=str(e))

    with session_scope() as s:
        row = s.get(Event, event_id)
        assert row is not None
        return TelemetryEventOut(
            id=row.id,
            name=row.name,
            session_id=row.session_id,
            user_id=row.user_id,
            ts=row.ts,
            props=row.props,
        )


@app.get("/approve")
def approve(token: str) -> Dict[str, Any]:
    from .security import verify_approval_token

    data = verify_approval_token(token)
    action = data.get("action")
    if action == "flip_flag":
        flag_name = data.get("flag")
        percent = int(data.get("percent", 100))
        if not flag_name:
            raise HTTPException(status_code=400, detail="flag required")
        with session_scope() as s:
            # Create or update deterministically by flag name to avoid unique constraint violations
            upsert_flag(
                session=s,
                name=flag_name,
                enabled=percent > 0,
                rollout_percent=percent,
                created_by="approval",
            )
        flags.clear_cache()
        return {"ok": True, "flag": flag_name, "percent": percent}
    return JSONResponse(status_code=200, content={"ok": True, "action": action})


@app.websocket("/ws/audio")
async def ws_audio(ws: WebSocket, session_id: str = "s-local", user_id: Optional[str] = None) -> None:
    await handle_audio_ws(ws, session_id=session_id, user_id=user_id)


@app.get("/experiments/{name}")
def get_experiment(name: str) -> Dict[str, Any]:
    exp = load_experiment(name)
    if not exp:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "name": exp.name,
        "hypothesis": exp.hypothesis,
        "metrics": exp.metrics,
        "unit": exp.unit,
        "sample_size": exp.sample_size,
        "guardrails": exp.guardrails,
        "SRM_check": exp.SRM_check,
    }


@app.post("/ops/notify_pr")
def notify_pr(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Webhook-style endpoint invoked by the host flusher after opening a PR.

    Expected payload: { slug, pr_number, branch, url }
    """
    slug = str(payload.get("slug", ""))
    branch = str(payload.get("branch", ""))
    pr_number = int(payload.get("pr_number", 0))
    url = str(payload.get("url", ""))
    if not slug or not branch or pr_number <= 0:
        raise HTTPException(status_code=400, detail="invalid payload")
    # Fire-and-forget: CTO + heads + auto-merge evaluator
    try:
        cto_review.delay(slug=slug, pr_number=pr_number, branch=branch, url=url)
        head_design.delay(slug=slug, pr_number=pr_number, branch=branch)
        head_product.delay(slug=slug, pr_number=pr_number, branch=branch)
        head_engineering.delay(slug=slug, pr_number=pr_number, branch=branch)
        auto_merge_if_safe.delay(slug=slug, pr_number=pr_number, branch=branch)
    except Exception:
        pass
    return {"ok": True}


