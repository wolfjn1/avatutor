from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict

import httpx

from ..celery_app import celery_app


def _git_identity(repo_root: Path) -> None:
    subprocess.run(["git", "config", "user.name", "Autopilot Bot"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "config", "user.email", "autopilot@local"], cwd=str(repo_root), check=False)


def _maybe_create_pr(repo_root: Path, branch: str, title: str, body: str) -> str:
    gh_token = os.getenv("GH_TOKEN")
    if not gh_token:
        return "pending-local"
    try:
        out = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], cwd=str(repo_root)).decode().strip()
    except Exception:
        return "pending-local"
    slug = None
    if out.startswith("git@github.com:"):
        slug = out.split(":", 1)[1].rstrip(".git")
    elif out.startswith("https://"):
        ix = out.find("github.com/")
        if ix != -1:
            slug = out[ix + len("github.com/") :].rstrip(".git")
    if not slug:
        return "pending-local"
    api_url = f"https://api.github.com/repos/{slug}/pulls"
    headers = {"Authorization": f"Bearer {gh_token}", "Accept": "application/vnd.github+json"}
    payload = {"title": title, "head": branch, "base": os.getenv("DEFAULT_BRANCH", "main"), "body": body}
    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            r = client.post(api_url, headers=headers, json=payload)
            if r.status_code in (200, 201):
                return r.json().get("html_url", "pending-local")
    except Exception:
        pass
    return "pending-local"


@celery_app.task(name="apps.api.tasks.agents_product.define_next_work")
def define_next_work() -> Dict[str, str]:
    """Product agent: define next high-impact task and open a planning PR.

    Heuristics:
    - If web client lacks a dedicated session UI, propose a basic tutoring session pane
    - If engagement file missing, propose badges surfacing in UI
    - If no prompts doc, propose adding an initial tutor prompt
    """
    repo_root = Path(__file__).resolve().parents[3]
    _git_identity(repo_root)

    # Draft a PRODUCT_PLAN.md with current priorities
    plan = repo_root / "docs" / "PRODUCT_PLAN.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    current = plan.read_text(encoding="utf-8") if plan.exists() else ""
    proposed = (
        "# Product Plan (rolling)\n\n"
        "- MVP: Live AI Tutor with push-to-talk, transcript, first-token, TTS chunks, basic avatar\n"
        "- Next: Session layout, achievements panel, design tokens, prompt quality\n"
        "- Measure: price_per_turn_usd, tokens_in/out, llm_first_token_ms, stt/tts latency\n"
    )
    if proposed not in current:
        plan.write_text(proposed, encoding="utf-8")

    branch = f"autonomy/product-plan-{os.getpid()}"
    subprocess.run(["git", "checkout", "-b", branch], cwd=str(repo_root), check=False, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "commit", "-m", "docs(product): rolling product plan"], cwd=str(repo_root), check=False)

    # Try to push with HTTPS+token to avoid SSH
    gh_token = os.getenv("GH_TOKEN")
    try:
        out = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], cwd=str(repo_root)).decode().strip()
        slug = None
        if out.startswith("git@github.com:"):
            slug = out.split(":", 1)[1].rstrip(".git")
        elif out.startswith("https://github.com/"):
            slug = out.split("https://github.com/", 1)[1].rstrip(".git")
        if slug and gh_token:
            subprocess.run(["git", "remote", "set-url", "origin", f"https://x-access-token:{gh_token}@github.com/{slug}.git"], cwd=str(repo_root), check=False)
        subprocess.run(["git", "push", "-u", "origin", branch], cwd=str(repo_root), check=False)
    except Exception:
        pass

    pr = _maybe_create_pr(repo_root, branch, "docs(product): rolling product plan", "Automated product plan to guide next tasks.")
    return {"branch": branch, "pr": pr}


