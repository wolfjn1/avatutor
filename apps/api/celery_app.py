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
    ],
)

celery_app.conf.task_queues = {
    "frontend": {},
    "api": {},
    "infra": {},
    "etl": {},
}

celery_app.conf.beat_schedule = {
    "daily-morning-brief": {
        "task": "apps.api.tasks.reports.generate_morning_brief",
        "schedule": 60.0 * 60.0 * 24.0,  # daily
        "options": {"queue": "infra"},
    },
    "cost-ux-tune-120m": {
        "task": "apps.api.tasks.autonomy.cost_ux_tune",
        "schedule": 60.0 * 120.0,  # every 120 minutes
        "options": {"queue": "infra"},
    },
    "frontend-polish-120m": {
        "task": "apps.api.tasks.agents_frontend.improve_web_ui",
        "schedule": 60.0 * 120.0,  # every 120 minutes
        "options": {"queue": "frontend"},
    },
    "backend-prompt-120m": {
        "task": "apps.api.tasks.agents_backend.improve_prompt_quality",
        "schedule": 60.0 * 120.0,
        "options": {"queue": "api"},
    },
    "backend-latency-120m": {
        "task": "apps.api.tasks.agents_backend.tune_latency_budgets",
        "schedule": 60.0 * 120.0,
        "options": {"queue": "infra"},
    },
}


