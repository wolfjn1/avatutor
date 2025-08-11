from __future__ import annotations

from ..celery_app import celery_app
from ..telemetry import canary_guardrails_ok
from ..feature_flags import flags
from sqlalchemy import select, update

from ..db import session_scope, FeatureFlag, upsert_flag, insert_event


@celery_app.task(name="apps.api.tasks.guardrails.canary_check")
def canary_check() -> bool:
    ok = canary_guardrails_ok()
    if not ok:
        # Auto rollback VOICE_AVATAR_MVP
        with session_scope() as s:
            # Update first; if no row, insert
            res = s.execute(
                update(FeatureFlag)
                .where(FeatureFlag.name == "VOICE_AVATAR_MVP")
                .values(enabled=False, rollout_percent=0)
            )
            if res.rowcount == 0:
                upsert_flag(
                    session=s,
                    name="VOICE_AVATAR_MVP",
                    enabled=False,
                    rollout_percent=0,
                    created_by="canary_check",
                )
            insert_event(
                session=s,
                name="canary.rollback",
                session_id="ops",
                user_id=None,
                props={"reason": "guardrails_breached"},
            )
        flags.clear_cache()
    return ok


@celery_app.task(name="apps.api.tasks.guardrails.canary_stepper")
def canary_stepper() -> str:
    """Escalate VOICE_AVATAR_MVP rollout percent 5 -> 25 -> 100 when guardrails OK, otherwise rollback.

    Returns the resulting percent as a string label (e.g., "rolled_back", "5", "25", "100").
    """
    if not canary_guardrails_ok():
        # Roll back fully
        with session_scope() as s:
            res = s.execute(
                update(FeatureFlag)
                .where(FeatureFlag.name == "VOICE_AVATAR_MVP")
                .values(enabled=False, rollout_percent=0)
            )
            if res.rowcount == 0:
                upsert_flag(
                    session=s,
                    name="VOICE_AVATAR_MVP",
                    enabled=False,
                    rollout_percent=0,
                    created_by="canary_stepper",
                )
            insert_event(
                session=s,
                name="canary.rollback",
                session_id="ops",
                user_id=None,
                props={"reason": "guardrails_breached"},
            )
        flags.clear_cache()
        return "rolled_back"

    # Guardrails OK: step up percent deterministically
    with session_scope() as s:
        row = s.scalar(select(FeatureFlag).where(FeatureFlag.name == "VOICE_AVATAR_MVP"))
        current = int(row.rollout_percent) if row else 0
        if current < 5:
            res = s.execute(
                update(FeatureFlag)
                .where(FeatureFlag.name == "VOICE_AVATAR_MVP")
                .values(enabled=True, rollout_percent=5)
            )
            if res.rowcount == 0:
                upsert_flag(
                    session=s,
                    name="VOICE_AVATAR_MVP",
                    enabled=True,
                    rollout_percent=5,
                    created_by="canary_stepper",
                )
            label = "5"
        elif current < 25:
            res = s.execute(
                update(FeatureFlag)
                .where(FeatureFlag.name == "VOICE_AVATAR_MVP")
                .values(enabled=True, rollout_percent=25)
            )
            if res.rowcount == 0:
                upsert_flag(
                    session=s,
                    name="VOICE_AVATAR_MVP",
                    enabled=True,
                    rollout_percent=25,
                    created_by="canary_stepper",
                )
            label = "25"
        elif current < 100:
            res = s.execute(
                update(FeatureFlag)
                .where(FeatureFlag.name == "VOICE_AVATAR_MVP")
                .values(enabled=True, rollout_percent=100)
            )
            if res.rowcount == 0:
                upsert_flag(
                    session=s,
                    name="VOICE_AVATAR_MVP",
                    enabled=True,
                    rollout_percent=100,
                    created_by="canary_stepper",
                )
            label = "100"
        else:
            label = "100"  # already at max
        insert_event(
            session=s,
            name="canary.step",
            session_id="ops",
            user_id=None,
            props={"from_percent": current, "to_percent": int(label)},
        )
    flags.clear_cache()
    return label


