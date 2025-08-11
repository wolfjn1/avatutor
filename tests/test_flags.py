from __future__ import annotations

from hashlib import sha256

from fastapi.testclient import TestClient

from apps.api.db import init_db, session_scope, upsert_flag
from apps.api.feature_flags import flags
from apps.api.main import app


def test_flag_toggle_and_percent_sticky() -> None:
    init_db()
    with session_scope() as s:
        upsert_flag(session=s, name="TEST_FLAG", enabled=True, rollout_percent=25)

    client = TestClient(app)
    r = client.get("/flags")
    assert r.status_code == 200

    # Sticky bucketing: same user id should keep decision
    user_a = "user-a"
    user_b = "user-b"

    a_enabled = flags.is_enabled("TEST_FLAG", user_id=user_a)
    b_enabled = flags.is_enabled("TEST_FLAG", user_id=user_b)
    # It is improbable both are False if percent=25, but not guaranteed; assert stickiness by hash mapping
    def bucket(uid: str) -> int:
        return int(sha256(uid.encode()).hexdigest()[:8], 16) % 100

    assert a_enabled == (bucket(user_a) < 25)
    assert b_enabled == (bucket(user_b) < 25)


def test_flag_get_and_put_updates_and_cache_invalidation() -> None:
    init_db()
    with session_scope() as s:
        upsert_flag(session=s, name="CACHE_TEST", enabled=False, rollout_percent=0)

    client = TestClient(app)

    # GET existing
    r = client.get("/flags/CACHE_TEST")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "CACHE_TEST"
    assert data["enabled"] is False
    assert data["rollout_percent"] == 0

    # Prime cache with disabled flag
    flags.is_enabled("CACHE_TEST", user_id="u1")

    # PUT update
    r2 = client.put("/flags/CACHE_TEST", json={"enabled": True, "rollout_percent": 100})
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["enabled"] is True
    assert data2["rollout_percent"] == 100

    # After update, cache should be cleared; re-evaluate and reflect new value
    assert flags.is_enabled("CACHE_TEST", user_id="u1") is True

