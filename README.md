# ai-tutor-autopilot

Production-ready monorepo for a Live AI Tutor platform (voice + avatar) with FastAPI, Celery, Postgres, Redis, MinIO, feature flags, telemetry, and CI policy gates.

- Quickstart: see `docs/QUICKSTART.md`
- Operations: see `docs/OPS.md`
- Autonomy & agentic improvement loop: see `docs/AUTONOMY.md`

## What’s included
- API (`apps/api`): FastAPI app, WebSocket audio endpoint (`/ws/audio`), feature flags, telemetry, approvals
- Workers (`celery`): scheduled reports, canary guardrails, DLQ sweeps
- Infrastructure (`infrastructure/`): Docker Compose stack (API, worker, beat, Postgres, Redis, MinIO, Caddy)
- Analytics (`analytics/`): events/metrics registries
- Sidecar agents (`apps/sidecar`): ops brain and roles (design/engineering/product/policy/research)
- Policy gates (`policy/`): commit and migration lint rules for CI/PRs

## Live tutor MVP
The default pipeline is wired with mocks for STT/LLM/TTS/Avatar to enable local testing. Replace mocks with real providers and gate rollout with the `VOICE_AVATAR_MVP` flag.

High-level flow:
1) Client streams mic audio to `/ws/audio?session_id=...&user_id=...`
2) Server emits partial transcripts, first LLM token, TTS chunks, avatar frames
3) Server records a `turn` event with timings and metrics

## Local dev in a hurry

1) Create `.env` (see `docs/QUICKSTART.md` for the template)
2) Bring up the stack:
   - `docker compose -f infrastructure/docker-compose.yml up -d --build`
3) Seed flags:
   - `docker compose -f infrastructure/docker-compose.yml exec api python scripts/seed.py`
4) Health check:
   - `curl -s http://localhost:8080/health | jq .`

## Next
- Implement real STT/LLM/TTS/Avatar providers under `apps/api/providers` (toggle via env flags)
- Add token/cost metrics to `turn` events
- Add a minimal web client for mic capture and avatar playback
- Enable agents to propose/critique/execute weekly improvements (see `docs/AUTONOMY.md`)

