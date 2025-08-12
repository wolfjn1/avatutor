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
    """Return recent commits on local branches matching refs/heads/autonomy/*.

    The previous implementation filtered by path (:(glob)autonomy/*), which only
    returns commits that touched files under an autonomy/ directory. Our agents
    create branches named autonomy/* that usually modify files across the repo,
    so we need to scan those branches explicitly.
    """
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    try:
        branches_raw = subprocess.check_output(
            [
                "git",
                "for-each-ref",
                "--format=%(refname:short)",
                "refs/heads/autonomy/*",
            ],
            cwd=str(repo_root),
        ).decode()
    except Exception:
        branches_raw = ""

    branches = [b.strip() for b in branches_raw.splitlines() if b.strip()]
    if not branches:
        return []

    lines: list[str] = []
    for br in branches:
        try:
            out = subprocess.check_output(
                [
                    "git",
                    "log",
                    br,
                    f"--since={since}",
                    "--pretty=%h %s",
                    "-n",
                    "50",
                ],
                cwd=str(repo_root),
            ).decode()
        except Exception:
            continue
        for ln in out.splitlines():
            ln = ln.strip()
            if ln:
                lines.append(f"{br}: {ln}")
    # De-duplicate while preserving order
    seen = set()
    deduped: list[str] = []
    for ln in lines:
        if ln not in seen:
            seen.add(ln)
            deduped.append(ln)
    return deduped


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


def _recent_prs(slug: str, minutes: int = 30) -> List[Dict[str, str]]:
    """Fetch recent PRs created or updated in the last N minutes.

    Requires public GitHub access; uses GH_TOKEN if available for higher limits.
    """
    if not slug:
        return []
    token = os.getenv("GH_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{slug}/pulls?state=open&sort=updated&direction=desc&per_page=50"
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
            r = client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    out: List[Dict[str, str]] = []
    for pr in data:
        try:
            updated_at = pr.get("updated_at") or pr.get("created_at")
            if not updated_at:
                continue
            # Parse ISO time
            ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if ts >= cutoff:
                out.append({
                    "number": str(pr.get("number")),
                    "title": str(pr.get("title", "")),
                    "url": str(pr.get("html_url", "")),
                    "branch": str(pr.get("head",{}).get("ref","")),
                })
        except Exception:
            continue
    return out


@celery_app.task(name="apps.api.tasks.chief_of_staff.progress_update")
def progress_update() -> Dict[str, str]:
    """Summarize shipped work (commits, PRs, reviews) in the last 30 minutes.

    Posts to Slack if configured; always records an event that can be fetched via /ops/cos_updates.
    """
    repo_root = Path(__file__).resolve().parents[3]
    commits = _collect_recent_autonomy_commits(repo_root, minutes=30)
    app_url = os.getenv("APP_BASE_URL", "http://localhost:8080")
    slug = _origin_slug(repo_root)
    prs_link = f"https://github.com/{slug}/pulls?sort=created&direction=desc" if slug else ""
    prs = _recent_prs(slug, minutes=30)

    lines: List[str] = []
    if commits:
        lines.append("Commits:")
        lines.extend(f"- {ln}" for ln in commits[:50])
    if prs:
        lines.append("PRs:")
        for pr in prs[:20]:
            lines.append(f"- #{pr['number']} {pr['title']} ({pr['branch']}) {pr['url']}")
    summary = "No new autonomy activity in the last 30 minutes." if not lines else "\n".join(lines)

    # Naive gap detection by keywords in commit subjects
    text = (" ".join(commits) + " " + " ".join(p.get("title","") for p in prs)).lower()
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
                    "items": len(commits) + len(prs),
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

    return {"items": str(len(commits) + len(prs)), "gaps": ",".join(gaps), "app_url": app_url}


