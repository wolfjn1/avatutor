from __future__ import annotations

import os
from typing import Dict, List

import httpx

from ..celery_app import celery_app
from .conflict_resolver import open_conflict_fix_pr
from .reviews import auto_merge_if_safe


def _gh_headers() -> Dict[str, str]:
    token = os.getenv("GH_TOKEN", "")
    headers: Dict[str, str] = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _list_open_prs(slug: str) -> List[Dict]:
    headers = _gh_headers()
    with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
        r = client.get(
            f"https://api.github.com/repos/{slug}/pulls",
            params={"state": "open", "per_page": 100},
            headers=headers,
        )
        r.raise_for_status()
        return list(r.json())


@celery_app.task(name="apps.api.tasks.pr_recheck.recheck_open_prs")
def recheck_open_prs() -> Dict[str, str]:
    """Poll GitHub for open PRs and drive conflict-fix and auto-merge.

    Lightweight backstop that ensures progress if GitHub mergeable_state
    is delayed or if earlier attempts were missed.
    """
    slug = os.getenv("GITHUB_SLUG", "wolfjn1/avatutor")
    token = os.getenv("GH_TOKEN", "")
    if not token:
        return {"ok": "false", "reason": "no_token"}

    opened = 0
    attempted_merge = 0
    try:
        prs = _list_open_prs(slug)
        with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
            for p in prs:
                head = p.get("head", {}).get("ref", "")
                if not head.startswith("autonomy/"):
                    continue
                prn = int(p.get("number", 0))
                # Fetch per-PR to ensure mergeable_state computed
                pr = client.get(
                    f"https://api.github.com/repos/{slug}/pulls/{prn}",
                    headers=_gh_headers(),
                ).json()
                state = pr.get("mergeable_state")
                labels = [l.get("name", "") for l in pr.get("labels", [])]

                if state == "dirty" or "needs-rebase-conflict" in labels:
                    open_conflict_fix_pr.delay(slug=slug, pr_number=prn, branch=head)
                    attempted_merge += 1
                else:
                    auto_merge_if_safe.delay(slug=slug, pr_number=prn, branch=head)
                    attempted_merge += 1
                opened += 1
    except Exception:
        return {"ok": "false", "reason": "exception"}

    return {"ok": "true", "checked": str(opened), "merge_attempts": str(attempted_merge)}


