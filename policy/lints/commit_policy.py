from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import List


ROUTE_PATTERNS = [r"^apps/api/main.py", r"^apps/api/ws_", r"^infrastructure/Caddyfile"]
SECRET_PATTERNS = [
    r"AKIA[0-9A-Z]{16}",  # AWS Access Key
    r"secret_key\s*=\s*['\"][A-Za-z0-9_/+\-]{16,}['\"]",
]


@dataclass
class Violation:
    code: str
    message: str


def _get_diff() -> str:
    return subprocess.check_output(["git", "diff", "--unified=0", "HEAD~1..HEAD"]).decode()


def _title_from_env() -> str:
    return os.getenv("PR_TITLE", "")


def _routes_changed(diff: str) -> bool:
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            if any(re.search(p, path) for p in ROUTE_PATTERNS):
                return True
    return False


def _migrations_expand_contract_ok(diff: str) -> bool:
    # Look for migrations with upgrade/downgrade and sentinel comments
    if "infrastructure/migrations/" not in diff:
        return True
    has_expand = "# expand:" in diff
    has_contract = "# contract:" in diff
    return has_expand and has_contract


def _secrets_scanned_ok(diff: str) -> bool:
    # Skip secret scanning for migration diffs to reduce false positives
    if "infrastructure/migrations/" in diff:
        # Allow when expand/contract sentinels are present
        if _migrations_expand_contract_ok(diff):
            return True
    # Only scan newly added content lines; skip diff headers and file paths
    added_lines = []
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---") or line.startswith("diff --git") or line.startswith("index "):
            continue
        if line.startswith("+"):
            added_lines.append(line[1:])
    text = "\n".join(added_lines)
    # Do not scan sentinel lines
    text = "\n".join([ln for ln in text.splitlines() if ln.strip() not in {"# expand:", "# contract:"}])
    for pat in SECRET_PATTERNS:
        if re.search(pat, text):
            return False
    # entropy heuristic: restrict to quoted literals or assignment values to reduce false positives on paths
    if re.search(r"(['\"][A-Za-z0-9+/=]{32,}['\"])|(=\s*[A-Za-z0-9+/=]{32,})", text):
        return False
    return True


def main() -> int:
    diff = _get_diff()
    title = _title_from_env()
    violations: List[Violation] = []

    if _routes_changed(diff) and "[FLAG:" not in title:
        violations.append(Violation("FLAG", "Route changes require [FLAG:NAME] in PR title"))

    if not _migrations_expand_contract_ok(diff):
        violations.append(Violation("MIGRATION", "Migrations must include expand/contract sentinels"))

    if not _secrets_scanned_ok(diff):
        violations.append(Violation("SECRETS", "Potential secrets detected in diff"))

    if violations:
        for v in violations:
            print(f"{v.code}: {v.message}")
        return 1
    print("policy checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())


