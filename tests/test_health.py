from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app


def test_health() -> None:
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "build" in data


