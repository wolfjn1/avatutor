from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict

from ..celery_app import celery_app


def _git_identity(repo_root: Path) -> None:
    subprocess.run(["git", "config", "user.name", "Autopilot Bot"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "config", "user.email", "autopilot@local"], cwd=str(repo_root), check=False)


@celery_app.task(name="apps.api.tasks.agents_design.improve_design_system")
def improve_design_system() -> Dict[str, str]:
    repo_root = Path(__file__).resolve().parents[3]
    _git_identity(repo_root)
    # Create or update a lightweight design tokens file for the web client
    tokens = repo_root / "web" / "tokens.css"
    tokens.parent.mkdir(parents=True, exist_ok=True)
    if not tokens.exists():
        tokens.write_text(
            ":root{--brand:#6b5bff;--accent:#00d2ff;--bg:#f9fafb;--text:#111827;--muted:#6b7280;}",
            encoding="utf-8",
        )
    index = repo_root / "web" / "index.html"
    try:
        html = index.read_text(encoding="utf-8") if index.exists() else ""
        if "tokens.css" not in html and "</head>" in html:
            html = html.replace("</head>", '<link rel="stylesheet" href="/tokens.css" /></head>')
            index.write_text(html, encoding="utf-8")
    except Exception:
        pass
    branch = f"autonomy/design-tokens"
    subprocess.run(["git", "checkout", "-B", branch], cwd=str(repo_root), check=False, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "commit", "-m", "feat(design): add base design tokens and wire to web"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=str(repo_root), check=False)
    return {"branch": branch}


