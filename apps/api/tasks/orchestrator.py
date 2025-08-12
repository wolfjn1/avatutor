from __future__ import annotations

from typing import Dict

from ..celery_app import celery_app
from ..db import insert_event, session_scope


def _dispatch_work_batch() -> Dict[str, str]:
    send = celery_app.send_task
    # Fan-out a compact batch covering FE/BE/design/engagement/cost/tutor
    send("apps.api.tasks.agents_frontend.improve_web_ui", queue="frontend")
    send("apps.api.tasks.agents_backend.improve_prompt_quality", queue="api")
    send("apps.api.tasks.agents_backend.tune_latency_budgets", queue="infra")
    send("apps.api.tasks.agents_design.improve_design_system", queue="frontend")
    send("apps.api.tasks.agents_engagement.improve_engagement", queue="frontend")
    send("apps.api.tasks.agents_tutor.improve_tutor_avatar", queue="api")
    send("apps.api.tasks.autonomy.cost_ux_tune", queue="infra")
    return {"queued": "true"}


@celery_app.task(name="apps.api.tasks.orchestrator.on_pr_merged")
def on_pr_merged(*, slug: str, pr_number: int, branch: str) -> Dict[str, str]:
    """Run immediately after a PR is auto-merged to keep the pipeline moving."""
    with session_scope() as s:
        insert_event(
            session=s,
            name="pipeline.on_merged",
            session_id="ops",
            user_id=None,
            props={"slug": slug, "pr": pr_number, "branch": branch},
        )
    return _dispatch_work_batch()


## keepalive removed per event-driven policy


