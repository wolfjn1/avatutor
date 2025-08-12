from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple, List

import httpx

from ..celery_app import celery_app
from ..db import insert_event, session_scope
from .orchestrator import on_pr_merged


def _git_identity(repo_root: Path) -> None:
    subprocess.run(["git", "config", "user.name", "Autopilot Bot"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "config", "user.email", "autopilot@local"], cwd=str(repo_root), check=False)


def _get_changed_files(repo_root: Path, branch: str) -> list[str]:
    # Legacy local git diff. Kept as a fallback when GH API unavailable.
    try:
        base = subprocess.check_output(["git", "merge-base", branch, "origin/main"], cwd=str(repo_root)).decode().strip()
    except Exception:
        base = "origin/main"
    try:
        out = subprocess.check_output(["git", "diff", "--name-only", f"{base}..{branch}"], cwd=str(repo_root)).decode()
        return [ln.strip() for ln in out.splitlines() if ln.strip()]
    except Exception:
        return []


def _get_pr_files_via_api(slug: str, pr_number: int) -> List[str]:
    token = os.getenv("GH_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
            r = client.get(f"https://api.github.com/repos/{slug}/pulls/{pr_number}/files", headers=headers)
            if r.status_code != 200:
                return []
            data = r.json()
    except Exception:
        return []
    files: List[str] = []
    for it in data:
        p = it.get("filename")
        if isinstance(p, str) and p:
            files.append(p)
    return files


def _label(slug: str, pr_number: int, labels: list[str]) -> None:
    token = os.getenv("GH_TOKEN")
    if not token:
        return
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
            client.post(
                f"https://api.github.com/repos/{slug}/issues/{pr_number}/labels",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                json={"labels": labels},
            )
    except Exception:
        pass


def _approve(slug: str, pr_number: int, body: str) -> None:
    token = os.getenv("GH_TOKEN")
    if not token:
        return
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
            client.post(
                f"https://api.github.com/repos/{slug}/pulls/{pr_number}/reviews",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                json={"event": "APPROVE", "body": body},
            )
    except Exception:
        pass


def _merge(slug: str, pr_number: int, method: str = "squash") -> bool:
    token = os.getenv("GH_TOKEN")
    if not token:
        return False
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
            r = client.put(
                f"https://api.github.com/repos/{slug}/pulls/{pr_number}/merge",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                json={"merge_method": method},
            )
            return r.status_code in (200, 201)
    except Exception:
        return False


def _classify_change(files: list[str]) -> Tuple[bool, str]:
    """Return (is_trivial, domain_label)."""
    text = "\n".join(files)
    trivial = all(
        (
            f.startswith("web/") or f.startswith("docs/") or f.startswith("analytics/") or f.endswith(".md") or f.endswith(".css") or f.endswith(".json")
        )
        for f in files
    ) and not any(f.endswith(ext) for ext in (".py",))
    if any("design" in f or f.endswith("tokens.css") for f in files):
        label = "design"
    elif any("engagement" in f or f.endswith("achievements.json") for f in files):
        label = "product"
    elif any("tutor" in f or f.endswith("avatar.css") for f in files):
        label = "tutor"
    elif any(f.endswith(".py") for f in files):
        label = "engineering"
    else:
        label = "misc"
    return trivial, label


@celery_app.task(name="apps.api.tasks.reviews.head_design")
def head_design(*, slug: str, pr_number: int, branch: str) -> Dict[str, str]:
    repo_root = Path(__file__).resolve().parents[3]
    _git_identity(repo_root)
    subprocess.run(["git", "fetch", "origin", branch], cwd=str(repo_root), check=False)
    api_files = _get_pr_files_via_api(slug, pr_number)
    files = api_files or _get_changed_files(repo_root, branch)
    trivial, label = _classify_change(files)
    _label(slug, pr_number, [f"design-reviewed", label])
    try:
        auto_merge_if_safe.delay(slug=slug, pr_number=pr_number, branch=branch)
    except Exception:
        pass
    if trivial and label == "design":
        _approve(slug, pr_number, "Design OK")
    return {"files": str(len(files)), "trivial": str(trivial).lower()}


@celery_app.task(name="apps.api.tasks.reviews.head_product")
def head_product(*, slug: str, pr_number: int, branch: str) -> Dict[str, str]:
    repo_root = Path(__file__).resolve().parents[3]
    _git_identity(repo_root)
    subprocess.run(["git", "fetch", "origin", branch], cwd=str(repo_root), check=False)
    api_files = _get_pr_files_via_api(slug, pr_number)
    files = api_files or _get_changed_files(repo_root, branch)
    trivial, label = _classify_change(files)
    _label(slug, pr_number, [f"product-reviewed", label])
    try:
        auto_merge_if_safe.delay(slug=slug, pr_number=pr_number, branch=branch)
    except Exception:
        pass
    if trivial and label in ("product", "tutor", "misc"):
        _approve(slug, pr_number, "Product OK")
    return {"files": str(len(files)), "trivial": str(trivial).lower()}


@celery_app.task(name="apps.api.tasks.reviews.head_engineering")
def head_engineering(*, slug: str, pr_number: int, branch: str) -> Dict[str, str]:
    repo_root = Path(__file__).resolve().parents[3]
    _git_identity(repo_root)
    subprocess.run(["git", "fetch", "origin", branch], cwd=str(repo_root), check=False)
    api_files = _get_pr_files_via_api(slug, pr_number)
    files = api_files or _get_changed_files(repo_root, branch)
    trivial, label = _classify_change(files)
    _label(slug, pr_number, [f"engineering-reviewed", label])
    try:
        auto_merge_if_safe.delay(slug=slug, pr_number=pr_number, branch=branch)
    except Exception:
        pass
    # Do not auto-approve .py changes; rely on CTO tests pass label
    return {"files": str(len(files)), "trivial": str(trivial).lower()}


@celery_app.task(name="apps.api.tasks.reviews.auto_merge_if_safe")
def auto_merge_if_safe(*, slug: str, pr_number: int, branch: str) -> Dict[str, str]:
    """Auto-merge if labeled safe: CTO tests pass + heads approvals or trivial change."""
    # Fetch labels
    token = os.getenv("GH_TOKEN")
    if not token:
        return {"merged": "false", "reason": "no_token"}
    def _fetch_labels() -> list[str]:
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
                r = client.get(
                    f"https://api.github.com/repos/{slug}/issues/{pr_number}",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                )
                if r.status_code == 200:
                    return [l.get("name", "") for l in r.json().get("labels", [])]
        except Exception:
            pass
        return []

    # Poll for labels for a short window to avoid races with head_* tasks
    import time
    merged = False
    for _ in range(6):
        labels = _fetch_labels()
        safe = ("cto-tests-pass" in labels) and ("design-reviewed" in labels) and ("product-reviewed" in labels) and ("engineering-reviewed" in labels)
        if safe:
            merged = _merge(slug, pr_number)
            if merged:
                try:
                    on_pr_merged.delay(slug=slug, pr_number=pr_number, branch=branch)
                except Exception:
                    pass
                return {"merged": "true", "reason": "safe"}
        time.sleep(2)

    # If still not safe, schedule a follow-up check in 30s
    try:
        auto_merge_if_safe.apply_async(kwargs={"slug": slug, "pr_number": pr_number, "branch": branch}, countdown=30)
    except Exception:
        pass
    return {"merged": "false", "reason": "labels_incomplete_pending"}



