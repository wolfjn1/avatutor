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


def _origin_slug(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], cwd=str(repo_root)).decode().strip()
    except Exception:
        return ""
    if out.startswith("git@github.com:"):
        s = out.split(":", 1)[1]
    elif out.startswith("https://github.com/"):
        s = out.split("https://github.com/", 1)[1]
    else:
        s = ""
    return s[:-4] if s.endswith(".git") else s


@celery_app.task(name="apps.api.tasks.chief_of_staff.progress_update")
def progress_update() -> Dict[str, str]:
    """Summarize shipped work in the last 30 minutes and post to Slack if configured."""
    repo_root = Path(__file__).resolve().parents[3]
    items = _collect_recent_autonomy_commits(repo_root, minutes=30)
    app_url = os.getenv("APP_BASE_URL", "http://localhost:8080")
    slug = _origin_slug(repo_root)
    prs_link = f"https://github.com/{slug}/pulls?sort=created&direction=desc" if slug else ""
    if not items:
        summary = "No new autonomy commits in the last 30 minutes."
    else:
        summary = "\n".join(f"- {ln}" for ln in items[:50])

    # Naive gap detection by keywords in commit subjects
    text = " ".join(items).lower()
    covered = {
        "design": ("design" in text or "tokens" in text),
        "engagement": ("engagement" in text or "badge" in text or "achievement" in text),
        "tutor": ("tutor" in text or "avatar" in text),
        "frontend": ("web" in text or "ui" in text),
        "backend": ("backend" in text or "prompt" in text or "latency" in text),
        "infra": ("infra" in text or "docker" in text or "compose" in text),
    }
    gaps = [k for k, v in covered.items() if not v]

    # Persist as an event for visibility
    try:
        with session_scope() as s:
            insert_event(
                session=s,
                name="cos.update",
                session_id="ops",
                user_id=None,
                props={
                    "items": len(items),
                    "summary": summary[:1000],
                    "gaps": gaps,
                    "app_url": app_url,
                    "prs": prs_link,
                },
            )
    except Exception:
        pass

    webhook = os.getenv("OPS_SLACK_WEBHOOK")
    if webhook:
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
                title = ":rocket: 30-min Product Update"
                appendix = f"\nApp: {app_url}" + (f"\nPRs: {prs_link}" if prs_link else "")
                if gaps:
                    appendix += "\nGaps: " + ", ".join(gaps)
                client.post(webhook, json={"text": f"{title}\n{summary}{appendix}"})
        except Exception:
            pass

    return {"items": str(len(items)), "gaps": ",".join(gaps), "app_url": app_url}


