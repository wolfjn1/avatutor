from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict

import httpx

from ..celery_app import celery_app


def _ensure_branch_and_commit(repo_root: Path, branch: str, message: str) -> str:
    subprocess.run(["git", "checkout", "-b", branch], cwd=str(repo_root), check=False, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "commit", "-m", message], cwd=str(repo_root), check=False)
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=str(repo_root), check=False)
    return branch


def _maybe_create_pr(repo_root: Path, branch: str, title: str, body: str) -> str:
    gh_token = os.getenv("GH_TOKEN")
    try:
        out = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], cwd=str(repo_root)).decode().strip()
        slug = None
        if out.startswith("git@github.com:"):
            slug = out.split(":", 1)[1].rstrip(".git")
        elif out.startswith("https://github.com/"):
            slug = out.split("https://github.com/", 1)[1].rstrip(".git")
        if not slug or not gh_token:
            return "pending-local"
        base = os.getenv("DEFAULT_BRANCH", "main")
        api_url = f"https://api.github.com/repos/{slug}/pulls"
        headers = {"Authorization": f"Bearer {gh_token}", "Accept": "application/vnd.github+json"}
        payload = {"title": title, "head": branch, "base": base, "body": body}
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            r = client.post(api_url, headers=headers, json=payload)
            if r.status_code in (200, 201):
                return r.json().get("html_url", "pending-local")
    except Exception:
        pass
    return "pending-local"


@celery_app.task(name="apps.api.tasks.agents_frontend.improve_web_ui")
def improve_web_ui() -> Dict[str, str]:
    repo_root = Path(__file__).resolve().parents[3]
    index = repo_root / "web" / "index.html"
    main_js = repo_root / "web" / "main.js"

    # Minimal visual polish and telemetry panel
    try:
        if index.exists():
            html = index.read_text(encoding="utf-8")
            if "Telemetry" not in html:
                html = html.replace(
                    "</body>",
                    """
<section style=\"margin-top:16px;padding:8px;border:1px solid #eee;border-radius:8px;\">
  <h3 style=\"margin-top:0\">Telemetry</h3>
  <div>Tokens in: <span id=\"tokens-in\">0</span> • Tokens out: <span id=\"tokens-out\">0</span> • Price: $<span id=\"price-usd\">0.0000</span></div>
</section>
</body>
""",
                )
                index.write_text(html, encoding="utf-8")
        if main_js.exists():
            js = main_js.read_text(encoding="utf-8")
            if "tokens-in" not in js:
                js += "\n// telemetry wiring\nwindow.updateTelemetry = (p)=>{try{document.getElementById('tokens-in').textContent=p.tokens_in||0;document.getElementById('tokens-out').textContent=p.tokens_out||0;document.getElementById('price-usd').textContent=(p.price_usd||0).toFixed? (p.price_usd||0).toFixed(4): (p.price_usd||0);}catch{}};\n"
                main_js.write_text(js, encoding="utf-8")
    except Exception:
        pass

    branch = f"autonomy/web-ui-improve-{os.getpid()}"
    subprocess.run(["git", "config", "user.name", "Autopilot Bot"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "config", "user.email", "autopilot@local"], cwd=str(repo_root), check=False)
    _ensure_branch_and_commit(repo_root, branch, "chore(frontend): UI polish and telemetry panel")
    # Force token-based remote for push if GH_TOKEN provided
    gh_token = os.getenv("GH_TOKEN")
    try:
        if gh_token:
            out = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], cwd=str(repo_root)).decode().strip()
            m = None
            if out.startswith("git@github.com:"):
                m = out.split(":", 1)[1]
            elif out.startswith("https://github.com/"):
                m = out.split("https://github.com/", 1)[1]
            if m and m.endswith(".git"):
                m = m[:-4]
            if m:
                https_token_url = f"https://x-access-token:{gh_token}@github.com/{m}.git"
                subprocess.run(["git", "remote", "set-url", "origin", https_token_url], cwd=str(repo_root), check=False)
                subprocess.run(["git", "push", "-u", "origin", branch], cwd=str(repo_root), check=False)
    except Exception:
        pass
    pr = _maybe_create_pr(repo_root, branch, "chore(frontend): UI polish", "Automated UI improvement.")
    return {"branch": branch, "pr": pr}


