from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.db import init_db, session_scope, upsert_flag, insert_event, Event
from apps.api.main import app
from apps.api.tasks.guardrails import canary_stepper


def _emit_turn_events(n_ok: int, n_err: int) -> None:
    with session_scope() as s:
        for i in range(n_ok):
            insert_event(
                session=s,
                name="turn",
                session_id=f"s{i}",
                user_id=f"u{i}",
                props={"total_turn_latency_ms": 800},
            )
        for j in range(n_err):
            insert_event(
                session=s,
                name="pipeline.error",
                session_id=f"se{j}",
                user_id=f"ue{j}",
                props={},
            )


def test_canary_stepper_escalates_then_rollback() -> None:
    init_db()
    # Ensure flag exists at 0%
    with session_scope() as s:
        upsert_flag(session=s, name="VOICE_AVATAR_MVP", enabled=False, rollout_percent=0)

    client = TestClient(app)
    # Clean slate events and add passing signals
    _emit_turn_events(n_ok=20, n_err=0)

    # First step: 0 -> 5
    label1 = canary_stepper()
    assert label1 == "5"
    r1 = client.get("/flags/VOICE_AVATAR_MVP")
    assert r1.status_code == 200
    assert r1.json()["rollout_percent"] == 5

    # Second step: 5 -> 25
    label2 = canary_stepper()
    assert label2 == "25"
    r2 = client.get("/flags/VOICE_AVATAR_MVP")
    assert r2.status_code == 200
    assert r2.json()["rollout_percent"] == 25

    # Third step: 25 -> 100
    label3 = canary_stepper()
    assert label3 == "100"
    r3 = client.get("/flags/VOICE_AVATAR_MVP")
    assert r3.status_code == 200
    assert r3.json()["rollout_percent"] == 100

    # Now emit failing signals to trigger rollback
    _emit_turn_events(n_ok=0, n_err=10)
    label4 = canary_stepper()
    assert label4 == "rolled_back"
    r4 = client.get("/flags/VOICE_AVATAR_MVP")
    assert r4.status_code == 200
    assert r4.json()["enabled"] is False
    assert r4.json()["rollout_percent"] == 0


