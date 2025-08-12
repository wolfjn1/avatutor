from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import httpx

from ..celery_app import celery_app
from ..db import insert_event, session_scope


def _collect_recent_autonomy_commits(repo_root: Path, minutes: int = 30) -> List[str]:
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    try:
        out = subprocess.check_output(
            [
                "git",
                "log",
                f"--since={since}",
                "--pretty=%h %s",
                "--",
                ":(glob)autonomy/*",
            ],
            cwd=str(repo_root),
        ).decode()
    except Exception:
        return []
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines


@celery_app.task(name="apps.api.tasks.chief_of_staff.progress_update")
def progress_update() -> Dict[str, str]:
    """Summarize shipped work in the last 30 minutes and post to Slack if configured."""
    repo_root = Path(__file__).resolve().parents[3]
    items = _collect_recent_autonomy_commits(repo_root, minutes=30)
    if not items:
        summary = "No new autonomy commits in the last 30 minutes."
    else:
        summary = "\n".join(f"- {ln}" for ln in items[:50])

    # Persist as an event for visibility
    try:
        with session_scope() as s:
            insert_event(
                session=s,
                name="cos.update",
                session_id="ops",
                user_id=None,
                props={"items": len(items), "summary": summary[:1000]},
            )
    except Exception:
        pass

    webhook = os.getenv("OPS_SLACK_WEBHOOK")
    if webhook:
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
                title = ":rocket: 30-min Product Update"
                client.post(webhook, json={"text": f"{title}\n{summary}"})
        except Exception:
            pass

    return {"items": str(len(items))}


