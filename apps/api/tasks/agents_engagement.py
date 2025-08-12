from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict

from ..celery_app import celery_app


def _git_identity(repo_root: Path) -> None:
    subprocess.run(["git", "config", "user.name", "Autopilot Bot"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "config", "user.email", "autopilot@local"], cwd=str(repo_root), check=False)


@celery_app.task(name="apps.api.tasks.agents_engagement.improve_engagement")
def improve_engagement() -> Dict[str, str]:
    repo_root = Path(__file__).resolve().parents[3]
    _git_identity(repo_root)
    # Add a simple achievements JSON to drive UI badges without backend changes
    data_dir = repo_root / "web"
    data_dir.mkdir(parents=True, exist_ok=True)
    achievements = data_dir / "achievements.json"
    if not achievements.exists():
        achievements.write_text(
            json.dumps(
                {
                    "badges": [
                        {"id": "first_session", "label": "First Session", "desc": "Completed your first tutoring session"},
                        {"id": "streak_3", "label": "3-Day Streak", "desc": "Showed up 3 days in a row"}
                    ]
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    main_js = data_dir / "main.js"
    try:
        js = main_js.read_text(encoding="utf-8") if main_js.exists() else ""
        if "achievements.json" not in js:
            js += "\nfetch('/achievements.json').then(r=>r.json()).then(d=>{window.achievements=d.badges||[];}).catch(()=>{});\n"
            main_js.write_text(js, encoding="utf-8")
    except Exception:
        pass
    branch = f"autonomy/engagement-badges"
    subprocess.run(["git", "checkout", "-B", branch], cwd=str(repo_root), check=False, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "commit", "-m", "feat(engagement): seed achievements and wire to UI"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=str(repo_root), check=False)
    return {"branch": branch}


