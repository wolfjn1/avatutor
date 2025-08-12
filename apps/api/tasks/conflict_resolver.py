from __future__ import annotations

import os
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List

import httpx

from ..celery_app import celery_app


SAFE_KEEP_PR_GLOBS = (
    "docs/",
    "web/",
    "analytics/",
    "README.md",
    ".md",
    ".css",
    ".json",
    ".yml",
    ".yaml",
)

SAFE_KEEP_MAIN_FILES = {"app.db", "celerybeat-schedule"}


def _matches_any(path: str, prefixes_or_suffixes: List[str]) -> bool:
    for pat in prefixes_or_suffixes:
        if pat.endswith("/") and path.startswith(pat):
            return True
        if path.endswith(pat) and not pat.endswith("/"):
            return True
    return False


def _open_pr(slug: str, base_branch: str, head_branch: str, title: str, body: str) -> str:
    token = os.getenv("GH_TOKEN", "")
    if not token:
        return ""
    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            r = client.post(
                f"https://api.github.com/repos/{slug}/pulls",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                json={"title": title, "head": head_branch, "base": base_branch, "body": body},
            )
            if r.status_code in (200, 201):
                return str(r.json().get("html_url", ""))
    except Exception:
        return ""
    return ""


@celery_app.task(name="apps.api.tasks.conflict_resolver.open_conflict_fix_pr")
def open_conflict_fix_pr(*, slug: str, pr_number: int, branch: str) -> Dict[str, str]:
    """Attempt to resolve trivial conflicts and open a helper PR against the dirty branch.

    - Clones PR branch to a temp dir via token HTTPS
    - Rebases onto origin/main
    - If conflicts: for files under SAFE_KEEP_* globs, keep PR or main version heuristically
    - Pushes fix branch and opens PR with base=<dirty branch>, head=autonomy/conflict-fix-<pr>
    """
    token = os.getenv("GH_TOKEN", "")
    if not token or not slug or not branch:
        return {"ok": "false", "reason": "no_token_or_slug"}

    tmp = Path(tempfile.mkdtemp(prefix=f"conflict-{pr_number}-"))
    fix_branch = f"autonomy/conflict-fix-{pr_number}"
    try:
        clone_url = f"https://x-access-token:{token}@github.com/{slug}.git"
        subprocess.run(["git", "clone", "--depth", "50", "--branch", branch, clone_url, str(tmp)], check=True)
        subprocess.run(["git", "config", "user.name", "Autopilot Bot"], cwd=str(tmp), check=True)
        subprocess.run(["git", "config", "user.email", "autopilot@local"], cwd=str(tmp), check=True)
        # Create fix branch
        subprocess.run(["git", "checkout", "-b", fix_branch.split("/")[-1]], cwd=str(tmp), check=True)
        subprocess.run(["git", "fetch", "origin", "main"], cwd=str(tmp), check=True)
        res = subprocess.run(["git", "rebase", "origin/main"], cwd=str(tmp))
        if res.returncode != 0:
            # Resolve trivial conflicts heuristically
            # List unresolved files
            out = subprocess.check_output(["git", "diff", "--name-only", "--diff-filter=U"], cwd=str(tmp)).decode()
            conflicted = [ln.strip() for ln in out.splitlines() if ln.strip()]
            for p in conflicted:
                # Choose main or PR version based on heuristics
                keep_pr = _matches_any(p, list(SAFE_KEEP_PR_GLOBS))
                keep_main = (Path(p).name in SAFE_KEEP_MAIN_FILES)
                if keep_pr and not keep_main:
                    # Stage PR version (ours = index 2 during rebase)
                    subprocess.run(["git", "checkout", "--ours", "--", p], cwd=str(tmp), check=False)
                else:
                    # Default to keeping main for non-listed files
                    subprocess.run(["git", "checkout", "--theirs", "--", p], cwd=str(tmp), check=False)
                subprocess.run(["git", "add", "--", p], cwd=str(tmp), check=False)
            # Continue rebase; if still conflicts, abort
            cont = subprocess.run(["git", "rebase", "--continue"], cwd=str(tmp))
            if cont.returncode != 0:
                subprocess.run(["git", "rebase", "--abort"], cwd=str(tmp), check=False)
                return {"ok": "false", "reason": "conflicts_remain"}

        # Push fix branch to origin
        push = subprocess.run(["git", "push", "origin", f"HEAD:refs/heads/{fix_branch}"], cwd=str(tmp))
        if push.returncode != 0:
            return {"ok": "false", "reason": "push_failed"}

        pr_url = _open_pr(
            slug,
            base_branch=branch,
            head_branch=fix_branch,
            title=f"fix: resolve conflicts for PR #{pr_number}",
            body=(
                "Automated conflict resolution helper.\n\n"
                "- Rebased on origin/main\n"
                "- Applied heuristics:\n"
                "  - keep PR for docs/web/analytics/markdown/css/json/yaml\n"
                "  - keep main for app.db/celerybeat-schedule\n"
            ),
        )
        return {"ok": "true", "helper_pr": pr_url or ""}
    except Exception:
        return {"ok": "false", "reason": "exception"}
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass


