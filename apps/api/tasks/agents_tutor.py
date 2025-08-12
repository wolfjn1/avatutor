from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict

from ..celery_app import celery_app


def _git_identity(repo_root: Path) -> None:
    subprocess.run(["git", "config", "user.name", "Autopilot Bot"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "config", "user.email", "autopilot@local"], cwd=str(repo_root), check=False)


@celery_app.task(name="apps.api.tasks.agents_tutor.improve_tutor_avatar")
def improve_tutor_avatar() -> Dict[str, str]:
    repo_root = Path(__file__).resolve().parents[3]
    _git_identity(repo_root)
    # Add a very small avatar CSS/JS hook for mouth open/close states driven by ws tts chunks
    web_dir = repo_root / "web"
    web_dir.mkdir(parents=True, exist_ok=True)
    avatar_css = web_dir / "avatar.css"
    if not avatar_css.exists():
        avatar_css.write_text(
            ".avatar-mouth{width:24px;height:12px;border-radius:6px;background:#111;margin:4px auto;transition:transform .08s;}.avatar-mouth.open{transform:scaleY(1.8);} .avatar{display:inline-block;padding:8px;border:1px solid #eee;border-radius:8px;background:#fff;}",
            encoding="utf-8",
        )
    index = web_dir / "index.html"
    try:
        html = index.read_text(encoding="utf-8") if index.exists() else ""
        if "avatar.css" not in html and "</head>" in html:
            html = html.replace("</head>", '<link rel="stylesheet" href="/avatar.css" /></head>')
        if "avatar-mouth" not in html and "</body>" in html:
            html = html.replace("</body>", '<div class="avatar"><div id="mouth" class="avatar-mouth"></div></div></body>')
        index.write_text(html, encoding="utf-8")
    except Exception:
        pass
    main_js = web_dir / "main.js"
    try:
        js = main_js.read_text(encoding="utf-8") if main_js.exists() else ""
        if "mouth" not in js:
            js += "\n// avatar mouth hook\nwindow.onTtsChunk=(size)=>{try{const m=document.getElementById('mouth');if(!m)return;m.classList.add('open');clearTimeout(window._mouthTimer);window._mouthTimer=setTimeout(()=>m.classList.remove('open'),80);}catch{}};\n"
            # naive patch: if tts chunk messages exist, call onTtsChunk in handler
            js += "\n(function(){const _wsSend=window.wsSendHook; window.wsSendHook=(msg)=>{ if(_wsSend) _wsSend(msg); }; if(window.onWsMessage){const prev=window.onWsMessage; window.onWsMessage=(m)=>{try{if(m && m.type==='tts_chunk'){window.onTtsChunk(m.size||1)}}catch{}; return prev(m);};}})();\n"
            main_js.write_text(js, encoding="utf-8")
    except Exception:
        pass
    branch = f"autonomy/tutor-avatar"
    subprocess.run(["git", "checkout", "-B", branch], cwd=str(repo_root), check=False, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "commit", "-m", "feat(tutor): add avatar mouth visual hook"], cwd=str(repo_root), check=False)
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=str(repo_root), check=False)
    return {"branch": branch}



