from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Optional

import httpx

from ..celery_app import celery_app
from ..db import insert_event, session_scope


def _get_origin_slug(repo_root: Path) -> Optional[str]:
    try:
        out = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], cwd=str(repo_root)).decode().strip()
    except Exception:
        return None
    m = re.search(r"github.com[:/](?P<slug>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:\.git)?$", out)
    return m.group("slug") if m else None


def _git_identity(repo_root: Path) -> None:
    subprocess.run(["git", "config", "user.name", "Autopilot Bot"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "config", "user.email", "autopilot@local"], cwd=str(repo_root), check=False)


def _add_labels(slug: str, pr_number: int, labels: list[str]) -> None:
    gh_token = os.getenv("GH_TOKEN")
    if not gh_token:
        return
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
            client.post(
                f"https://api.github.com/repos/{slug}/issues/{pr_number}/labels",
                headers={"Authorization": f"Bearer {gh_token}", "Accept": "application/vnd.github+json"},
                json={"labels": labels},
            )
    except Exception:
        pass


@celery_app.task(name="apps.api.tasks.cto_review.cto_review")
def cto_review(*, slug: str, pr_number: int, branch: str, url: str) -> Dict[str, str]:
    """CTO review: checkout branch, run tests, label PR based on results, log event."""
    repo_root = Path(__file__).resolve().parents[3]
    _git_identity(repo_root)
    # Capture current branch
    try:
        current = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(repo_root)).decode().strip()
    except Exception:
        current = "main"

    ok = False
    try:
        subprocess.run(["git", "fetch", "origin", branch], cwd=str(repo_root), check=False)
        subprocess.run(["git", "checkout", branch], cwd=str(repo_root), check=False)
        # Run tests with safe mocks
        res = subprocess.run(["bash", "-lc", "scripts/run_tests_safe.sh"], cwd=str(repo_root), capture_output=True, text=True)
        ok = res.returncode == 0
    finally:
        subprocess.run(["git", "checkout", current], cwd=str(repo_root), check=False)

    # Label PR
    try:
        if ok:
            _add_labels(slug, pr_number, ["cto-tests-pass"])
        else:
            _add_labels(slug, pr_number, ["cto-tests-failed"])
    except Exception:
        pass

    # Log an event
    try:
        with session_scope() as s:
            insert_event(
                session=s,
                name="cto.review",
                session_id="ops",
                user_id=None,
                props={"branch": branch, "pr": pr_number, "ok": ok, "url": url},
            )
    except Exception:
        pass

    return {"ok": str(ok).lower()}




