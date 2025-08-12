from __future__ import annotations

import os
from typing import Any, Dict, Optional

import structlog
from fastapi import Depends, FastAPI, HTTPException, WebSocket
from fastapi.responses import JSONResponse, HTMLResponse

from .celery_app import celery_app  # noqa: F401  # ensure celery is importable
from .db import Event, FeatureFlag, init_db, session_scope, upsert_flag
from .feature_flags import flags
from .schemas import FlagCreate, FlagOut, FlagUpdate, TelemetryEventIn, TelemetryEventOut
from .experiments import load_experiment
from .telemetry import track_event
from .ws_audio import handle_audio_ws
from .tasks.cto_review import cto_review
from .tasks.orchestrator import on_pr_merged
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


@app.get("/ops/cos_updates")
def cos_updates(limit: int = 10, format: str = "html"):
    """Chief of Staff updates and live worker/PR status.

    - HTML view (default): dashboard showing workers and active PR review tasks.
    - JSON view: set ?format=json for the raw CoS updates payload.
    """
    # Fetch latest CoS updates from the DB
    with session_scope() as s:
        rows = (
            s.query(Event)
            .filter(Event.name == "cos.update")
            .order_by(Event.id.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )
        updates = [
            {
                "id": r.id,
                "ts": r.ts,
                "items": r.props.get("items"),
                "summary": r.props.get("summary"),
                "gaps": r.props.get("gaps"),
                "app_url": r.props.get("app_url"),
                "prs": r.props.get("prs"),
            }
            for r in rows
        ]

    if format.lower() == "json":
        return {"updates": updates}

    # Build live worker/PR view using Celery inspect
    try:
        insp = celery_app.control.inspect(timeout=1.0)
        active = insp.active() or {}
        stats = insp.stats() or {}
    except Exception:
        active = {}
        stats = {}

    # Render minimal HTML dashboard
    def _escape(s: Any) -> str:
        try:
            return str(s).replace("<", "&lt;").replace(">", "&gt;")
        except Exception:
            return ""

    rows_html: list[str] = []
    if not active:
        rows_html.append("<tr><td colspan=4>Idle (no active tasks)</td></tr>")
    else:
        import ast
        for worker, tasks in active.items():
            meta = stats.get(worker, {}) if isinstance(stats, dict) else {}
            concurrency = meta.get("pool", {}).get("max-concurrency") or meta.get("concurrency") or "?"
            if not tasks:
                rows_html.append(f"<tr><td>{_escape(worker)}</td><td>idle</td><td>-</td><td>-</td></tr>")
                continue
            for t in tasks:
                name = t.get("name", "?")
                kwargs = t.get("kwargs", {})
                if isinstance(kwargs, str):
                    try:
                        kwargs = ast.literal_eval(kwargs)
                    except Exception:
                        kwargs = {"raw": kwargs}
                pr = kwargs.get("pr_number") or kwargs.get("pr") or "-"
                branch = kwargs.get("branch", "-")
                slug = kwargs.get("slug", "-")
                rows_html.append(
                    f"<tr>"
                    f"<td>{_escape(worker)}<br/><small>conc: {_escape(concurrency)}</small></td>"
                    f"<td>{_escape(name)}</td>"
                    f"<td>PR {_escape(pr)}</td>"
                    f"<td>{_escape(branch)}<br/><small>{_escape(slug)}</small></td>"
                    f"</tr>"
                )

    html = f"""
    <html>
      <head>
        <meta http-equiv="refresh" content="5" />
        <title>Ops Dashboard</title>
        <style>
          body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif; margin: 20px; }}
          h1 {{ margin: 0 0 10px 0; }}
          table {{ border-collapse: collapse; width: 100%; }}
          th, td {{ border: 1px solid #ddd; padding: 8px; }}
          th {{ background: #f4f6f8; text-align: left; }}
          .section {{ margin-top: 24px; }}
          pre {{ white-space: pre-wrap; }}
        </style>
      </head>
      <body>
        <h1>Ops Dashboard</h1>
        <div class="section">
          <h2>Workers (live)</h2>
          <table>
            <thead>
              <tr><th>Worker</th><th>Task</th><th>PR</th><th>Branch</th></tr>
            </thead>
            <tbody>
              {''.join(rows_html)}
            </tbody>
          </table>
        </div>
        <div class="section">
          <h2>Chief of Staff (last {len(updates)} updates)</h2>
          <pre>{_escape(updates)}</pre>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=200)


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
        # Also enqueue next batch on PR opened to keep momentum even before merge
        on_pr_merged.delay(slug=slug, pr_number=pr_number, branch=branch)
    except Exception:
        pass
    return {"ok": True}


