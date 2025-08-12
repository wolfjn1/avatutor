from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Optional

import httpx

from ..celery_app import celery_app
from ...sidecar.ops_brain import run_daily
from ..db import session_scope, insert_event


def _get_origin_slug(repo_root: Path) -> Optional[str]:
    try:
        out = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], cwd=str(repo_root)).decode().strip()
    except Exception:
        return None
    # Support ssh and https remotes
    m = re.search(r"github.com[:/](?P<slug>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:\.git)?$", out)
    if not m:
        return None
    slug = m.group("slug")
    if slug.endswith(".git"):
        slug = slug[:-4]
    return slug


def _get_default_branch(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], cwd=str(repo_root)).decode().strip()
        if "/" in out:
            return out.rsplit("/", 1)[-1]
    except Exception:
        pass
    return os.getenv("DEFAULT_BRANCH", "main")


@celery_app.task(name="apps.api.tasks.autonomy.cost_ux_tune")
def cost_ux_tune() -> Dict[str, str]:
    """Run weekly autonomy loop: propose -> critique -> persist decision and prep PR.

    If no remote or GH_TOKEN present, create a local branch and print next steps.
    """
    result = run_daily()

    # Minimal PR bot skeleton
    repo_root = Path(__file__).resolve().parents[3]
    gh_token = os.getenv("GH_TOKEN")
    branch = f"autonomy/proposal-{os.getpid()}"
    pr_url = "pending-local"
    try:
        # Ensure repo identity for commits
        subprocess.run(["git", "config", "user.name", "Autopilot Bot"], cwd=str(repo_root), check=False)
        subprocess.run(["git", "config", "user.email", "autopilot@local"], cwd=str(repo_root), check=False)
        subprocess.run(["git", "checkout", "-b", branch], cwd=str(repo_root), check=False, capture_output=True)
        # Run tests safely (force mocks) and lints
        subprocess.run(["bash", "-lc", "scripts/run_tests_safe.sh"], cwd=str(repo_root), check=False)
        subprocess.run(["ruff", "check", "."], cwd=str(repo_root), check=False)
        subprocess.run(["mypy", "apps"], cwd=str(repo_root), check=False)
        # Commit if any changes were made by the loop (none by default)
        subprocess.run(["git", "add", "-A"], cwd=str(repo_root), check=False)
        subprocess.run(["git", "commit", "-m", "chore: weekly cost/UX tune [FLAG:VOICE_AVATAR_MVP]"], cwd=str(repo_root), check=False)
        # Push and attempt to create a PR if possible
        origin_slug = _get_origin_slug(repo_root)
        if gh_token and origin_slug:
            https_token_url = f"https://x-access-token:{gh_token}@github.com/{origin_slug}.git"
            subprocess.run(["git", "remote", "set-url", "origin", https_token_url], cwd=str(repo_root), check=False)
            subprocess.run(["git", "push", "-u", "origin", branch], cwd=str(repo_root), check=False)
            base = _get_default_branch(repo_root)
            title = "chore: weekly cost/UX tune [FLAG:VOICE_AVATAR_MVP]"
            body = f"Autonomy run; winner: {result.get('winner','')}"
            api_url = f"https://api.github.com/repos/{origin_slug}/pulls"
            headers = {"Authorization": f"Bearer {gh_token}", "Accept": "application/vnd.github+json"}
            payload = {"title": title, "head": branch, "base": base, "body": body}
            try:
                with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
                    r = client.post(api_url, headers=headers, json=payload)
                    if r.status_code in (200, 201):
                        pr_url = r.json().get("html_url", pr_url)
            except Exception:
                pass
    except Exception:
        pr_url = "error"

    # Log an autonomy event for operator visibility
    try:
        with session_scope() as s:
            insert_event(
                session=s,
                name="autonomy.proposal",
                session_id="ops",
                user_id=None,
                props={"winner": result.get("winner", ""), "branch": branch, "pr_url": pr_url},
            )
    except Exception:
        pass

    # Optional Slack notification
    webhook = os.getenv("OPS_SLACK_WEBHOOK")
    if webhook:
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
                text = f"Autonomy proposal ready: winner={result.get('winner','')}, branch={branch}, pr={pr_url}"
                client.post(webhook, json={"text": text})
        except Exception:
            pass

    return {"winner": result.get("winner", ""), "pr": pr_url}


