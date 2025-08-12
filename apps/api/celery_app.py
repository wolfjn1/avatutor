from __future__ import annotations

import os
from celery import Celery


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "ai_tutor",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "apps.api.tasks.reports",
        "apps.api.tasks.dlq",
        "apps.api.tasks.guardrails",
        "apps.api.tasks.autonomy",
        "apps.api.tasks.agents_frontend",
        "apps.api.tasks.agents_backend",
        "apps.api.tasks.agents_design",
        "apps.api.tasks.agents_engagement",
        "apps.api.tasks.agents_tutor",
        "apps.api.tasks.chief_of_staff",
        "apps.api.tasks.cto_review",
        "apps.api.tasks.reviews",
        "apps.api.tasks.orchestrator",
        "apps.api.tasks.conflict_resolver",
    ],
)

celery_app.conf.task_queues = {
    "frontend": {},
    "api": {},
    "infra": {},
    "etl": {},
}

# Ensure tasks without an explicit route/queue are actually consumed by our worker
# which listens on "api,frontend,infra,etl". The Celery default queue is "celery",
# and our worker does not bind to it. Setting this avoids orphaned tasks.
celery_app.conf.task_default_queue = "api"

# Keepalive orchestrator: backstops idle periods (runs every 2 minutes)
celery_app.conf.beat_schedule = {
    "daily-morning-brief": {
        "task": "apps.api.tasks.reports.generate_morning_brief",
        "schedule": 60.0 * 60.0 * 24.0,  # daily
        "options": {"queue": "infra"},
    },
    "cos-progress-30m": {
        "task": "apps.api.tasks.chief_of_staff.progress_update",
        "schedule": 60.0 * 30.0,
        "options": {"queue": "infra"},
    },
}


