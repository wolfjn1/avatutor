from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.api.db import init_db, session_scope, upsert_flag, Event
from apps.api.main import app


def test_ws_audio_stub_turn_event() -> None:
    init_db()
    with session_scope() as s:
        upsert_flag(session=s, name="VOICE_AVATAR_MVP", enabled=True, rollout_percent=100)

    client = TestClient(app)
    with client.websocket_connect("/ws/audio?session_id=s1&user_id=u1") as ws:
        ws.send_bytes(b"abcd")
        ws.send_bytes(b"efgh")
        messages = []
        for _ in range(8):
            data = ws.receive_text()
            messages.append(json.loads(data))
        # There should be partials and tts/avatar chunks and done
        types = {m["type"] for m in messages if "type" in m}
        assert "partial_transcript" in types
        assert "tts_chunk" in types
        assert "avatar_chunk" in types
        assert "done" in types
    # Ensure exactly one turn event recorded
    with session_scope() as s:
        count = s.query(Event).filter(Event.name == "turn").count()
        assert count == 1


def test_ws_audio_timing_ranges() -> None:
    init_db()
    with session_scope() as s:
        upsert_flag(session=s, name="VOICE_AVATAR_MVP", enabled=True, rollout_percent=100)

    client = TestClient(app)
    with client.websocket_connect("/ws/audio?session_id=s2&user_id=u2") as ws:
        ws.send_bytes(b"abcd")
        ws.send_bytes(b"efgh")
        # drain messages
        for _ in range(8):
            ws.receive_text()

    with session_scope() as s:
        ev = (
            s.query(Event)
            .filter(Event.name == "turn")
            .order_by(Event.id.desc())
            .first()
        )
        assert ev is not None
        props = ev.props
        # presence and types
        for key in [
            "stt_latency_ms",
            "llm_first_token_ms",
            "tts_synth_time_ms",
            "total_turn_latency_ms",
        ]:
            assert key in props
            assert isinstance(props[key], int)

        stt = props["stt_latency_ms"]
        llm = props["llm_first_token_ms"]
        tts = props["tts_synth_time_ms"]
        total = props["total_turn_latency_ms"]

        # reasonable ranges (allow generous headroom for CI variance)
        assert 0 <= stt <= 3000
        assert 0 <= llm <= 5000
        assert 0 <= tts <= 5000
        assert 0 < total <= 10000

        # ordering relationships
        assert llm >= stt
        assert total >= llm
        assert total >= tts


