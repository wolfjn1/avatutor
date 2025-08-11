from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.db import init_db, session_scope, upsert_flag
from apps.api.main import app
from apps.api.security import mint_approval_token


def _ensure_flag_disabled() -> None:
    with session_scope() as s:
        upsert_flag(session=s, name="VOICE_AVATAR_MVP", enabled=False, rollout_percent=0)


def test_approve_flip_flag_enable_percent() -> None:
    init_db()
    _ensure_flag_disabled()

    client = TestClient(app)
    token = mint_approval_token({
        "action": "flip_flag",
        "flag": "VOICE_AVATAR_MVP",
        "percent": 25,
    })

    r = client.get(f"/approve?token={token}")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["flag"] == "VOICE_AVATAR_MVP"
    assert data["percent"] == 25

    r2 = client.get("/flags/VOICE_AVATAR_MVP")
    assert r2.status_code == 200
    body = r2.json()
    assert body["enabled"] is True
    assert body["rollout_percent"] == 25


def test_approve_flip_flag_disable_with_zero_percent() -> None:
    init_db()
    _ensure_flag_disabled()

    client = TestClient(app)
    token = mint_approval_token({
        "action": "flip_flag",
        "flag": "VOICE_AVATAR_MVP",
        "percent": 0,
    })

    r = client.get(f"/approve?token={token}")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["flag"] == "VOICE_AVATAR_MVP"
    assert data["percent"] == 0

    r2 = client.get("/flags/VOICE_AVATAR_MVP")
    assert r2.status_code == 200
    body = r2.json()
    assert body["enabled"] is False
    assert body["rollout_percent"] == 0



