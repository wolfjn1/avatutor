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


def _push_with_token(repo_root: Path, branch: str) -> None:
    gh_token = os.getenv("GH_TOKEN")
    if not gh_token:
        return
    try:
        out = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], cwd=str(repo_root)).decode().strip()
    except Exception:
        return
    slug = None
    if out.startswith("git@github.com:"):
        slug = out.split(":", 1)[1]
    elif out.startswith("https://github.com/"):
        slug = out.split("https://github.com/", 1)[1]
    if not slug:
        return
    if slug.endswith(".git"):
        slug = slug[:-4]
    owner = slug.split("/", 1)[0]
    https_url = f"https://{owner}:{gh_token}@github.com/{slug}.git"
    subprocess.run(["git", "remote", "set-url", "origin", https_url], cwd=str(repo_root), check=False)
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=str(repo_root), check=False)


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
        slug = out.split(":", 1)[1]
    elif out.startswith("https://"):
        # strip protocol and credentials
        ix = out.find("github.com/")
        if ix != -1:
            slug = out[ix + len("github.com/") :]
    if not slug:
        return "pending-local"
    if slug.endswith(".git"):
        slug = slug[:-4]
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


@celery_app.task(name="apps.api.tasks.agents_backend.improve_prompt_quality")
def improve_prompt_quality() -> Dict[str, str]:
    repo_root = Path(__file__).resolve().parents[3]
    _git_identity(repo_root)
    prompts_dir = repo_root / "docs" / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    f = prompts_dir / "backend_system_prompt.md"
    if not f.exists():
        f.write_text(
            """# Backend System Prompt (Initial)

- Goal: High-quality, concise tutoring with chain-of-thought hidden, and structured steps for explanations.
- Style: Encouraging, step-by-step guidance; avoid solving entirely without student input.
- Latency: Prefer short, incremental responses; stream early.
""",
            encoding="utf-8",
        )
    branch = f"autonomy/backend-prompt-{os.getpid()}"
    subprocess.run(["git", "checkout", "-b", branch], cwd=str(repo_root), check=False, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "commit", "-m", "chore(backend): add initial system prompt"], cwd=str(repo_root), check=False)
    _push_with_token(repo_root, branch)
    pr = _maybe_create_pr(repo_root, branch, "chore(backend): add initial system prompt", "Automated prompt scaffold.")
    return {"branch": branch, "pr": pr}


@celery_app.task(name="apps.api.tasks.agents_backend.tune_latency_budgets")
def tune_latency_budgets() -> Dict[str, str]:
    repo_root = Path(__file__).resolve().parents[3]
    _git_identity(repo_root)
    proj = repo_root / "agents" / "projects" / "ai-tutor.yaml"
    # append a note; avoid breaking structure
    try:
        txt = proj.read_text(encoding="utf-8")
        if "# tuned" not in txt:
            txt += "\n# tuned: budgets reviewed at runtime by autonomy\n"
            proj.write_text(txt, encoding="utf-8")
    except Exception:
        pass
    branch = f"autonomy/backend-latency-{os.getpid()}"
    subprocess.run(["git", "checkout", "-b", branch], cwd=str(repo_root), check=False, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "commit", "-m", "chore(backend): latency budgets marker"], cwd=str(repo_root), check=False)
    _push_with_token(repo_root, branch)
    pr = _maybe_create_pr(repo_root, branch, "chore(backend): latency budgets marker", "Automated latency tuning scaffold.")
    return {"branch": branch, "pr": pr}


