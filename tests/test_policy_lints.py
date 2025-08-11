from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
import sys


def run_policy(diff: str, title: str = "") -> int:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "apps/api").mkdir(parents=True, exist_ok=True)
        (repo / "policy/lints").mkdir(parents=True, exist_ok=True)
        script = (repo / "policy/lints/commit_policy.py")
        script.write_text((Path("policy/lints/commit_policy.py").read_text()))
        # Mock git diff by writing a shell script that prints diff
        (repo / ".git").mkdir()
        sh = (repo / "git")
        sh.write_text("""#!/usr/bin/env bash
if [[ "$1" == "diff" ]]; then
  cat <<'EOF'
""" + diff + "\nEOF\n" + "fi\n")
        os.chmod(sh, 0o755)
        env = os.environ.copy()
        env["PATH"] = f"{repo}:{env['PATH']}"
        env["PR_TITLE"] = title
        return subprocess.call([sys.executable, str(script)], cwd=repo, env=env)


def test_flag_title_required_for_route_changes() -> None:
    diff = """
diff --git a/apps/api/main.py b/apps/api/main.py
--- a/apps/api/main.py
+++ b/apps/api/main.py
@@
+ @app.get('/new')
    pass
""".strip()
    rc = run_policy(diff, title="feat: add route")
    assert rc == 1
    rc2 = run_policy(diff, title="feat: add route [FLAG:VOICE_AVATAR_MVP]")
    assert rc2 == 0


def test_migration_expand_contract_required() -> None:
    diff = """
diff --git a/infrastructure/migrations/versions/0002_add_table.py b/infrastructure/migrations/versions/0002_add_table.py
--- a/infrastructure/migrations/versions/0002_add_table.py
+++ b/infrastructure/migrations/versions/0002_add_table.py
@@
+ def upgrade():
+     pass
    
""".strip()
    rc = run_policy(diff, title="chore: migration")
    assert rc == 1
    diff_ok = diff + "\n# expand:\n# contract:\n"
    rc2 = run_policy(diff_ok, title="chore: migration")
    assert rc2 == 0


def test_secret_scan() -> None:
    diff = """
diff --git a/apps/api/secret.py b/apps/api/secret.py
--- a/apps/api/secret.py
+++ b/apps/api/secret.py
@@
+ SECRET = 'AKIAABCDEFGHIJKLMNOP'
""".strip()
    rc = run_policy(diff, title="chore: secret test")
    assert rc == 1


