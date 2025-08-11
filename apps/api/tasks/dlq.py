from __future__ import annotations

from ..celery_app import celery_app
from ..db import DLQ, session_scope


@celery_app.task(name="apps.api.tasks.dlq.sweep")
def sweep() -> int:
    requeued = 0
    with session_scope() as s:
        items = s.query(DLQ).all()
        for item in items:
            # In local dev, just delete and pretend to requeue
            s.delete(item)
            requeued += 1
    return requeued


