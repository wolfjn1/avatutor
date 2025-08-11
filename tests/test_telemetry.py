from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.db import init_db
from apps.api.main import app


@pytest.fixture(autouse=True)
def _setup_db() -> None:
    init_db()


def test_rejects_unknown_event() -> None:
    client = TestClient(app)
    r = client.post(
        "/telemetry/track",
        json={"name": "unknown", "session_id": "s1", "user_id": "u1", "props": {}},
    )
    assert r.status_code == 400


def test_accepts_known_event_and_persists() -> None:
    client = TestClient(app)
    payload = {
        "name": "session_started",
        "session_id": "s1",
        "user_id": "u1",
        "props": {"subject": "math", "entry_point": "test"},
    }
    r = client.post("/telemetry/track", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] >= 1
    assert data["name"] == "session_started"


def test_session_ended_requires_fields_and_extra_props_preserved() -> None:
    client = TestClient(app)
    # Missing required field should 400
    missing = {
        "name": "session_ended",
        "session_id": "s-end",
        "user_id": "u1",
        # duration_ms missing
        "props": {"reason": "user_exit"},
    }
    r1 = client.post("/telemetry/track", json=missing)
    assert r1.status_code == 400

    # Provide all required, include an extra non-schema prop in props
    payload = {
        "name": "session_ended",
        "session_id": "s-end",
        "user_id": "u1",
        "props": {"duration_ms": 1234, "reason": "user_exit", "extra_info": "kept"},
    }
    r2 = client.post("/telemetry/track", json=payload)
    assert r2.status_code == 200
    data = r2.json()
    assert data["name"] == "session_ended"
    # props_extra should carry extra fields
    assert "props_extra" in data["props"]
    assert data["props"]["props_extra"]["extra_info"] == "kept"


def test_interruption_requires_type() -> None:
    client = TestClient(app)
    bad = {"name": "interruption", "session_id": "s1", "user_id": "u1", "props": {}}
    r1 = client.post("/telemetry/track", json=bad)
    assert r1.status_code == 400
    ok = {
        "name": "interruption",
        "session_id": "s1",
        "user_id": "u1",
        "props": {"type": "barge_in", "some": "extra"},
    }
    r2 = client.post("/telemetry/track", json=ok)
    assert r2.status_code == 200


