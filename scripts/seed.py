from __future__ import annotations

from apps.api.db import init_db, session_scope, upsert_flag


def main() -> None:
    init_db()
    with session_scope() as s:
        upsert_flag(session=s, name="VOICE_AVATAR_MVP", description="Enable WS audio MVP", enabled=False, rollout_percent=0, created_by="seed")
        upsert_flag(session=s, name="PUSH_TO_TALK", description="Use push to talk input", enabled=True, rollout_percent=100, created_by="seed")
        upsert_flag(session=s, name="VAD_BARGE_IN", description="Enable VAD-based barge-in", enabled=False, rollout_percent=0, created_by="seed")
    print("Seeded feature flags")


if __name__ == "__main__":
    main()


