## AI Tutor Autopilot Docs

- Quickstart: `docs/QUICKSTART.md`
- Ops: `docs/OPS.md`
  - See also: `docs/AUTONOMY.md`
- Analytics Registry: `analytics/events.yml`
- Metrics: `analytics/metrics.yml`
- Experiments: `docs/experiments/`


### API overview

- Health
  - GET `/health`

- Feature Flags
  - GET `/flags`: list all flags
  - POST `/flags`: create or update by name (idempotent). Accepts `FlagCreate | FlagUpdate`
  - GET `/flags/{name}`: typed `FlagOut`
  - PUT `/flags/{name}`: typed `FlagOut`, invalidates in-proc cache

- Telemetry
  - POST `/telemetry/track`: validates against `analytics/events.yml`, persists to DB; extra properties are preserved under `props.props_extra`

- Experiments
  - GET `/experiments/{name}`

- Approvals
  - GET `/approve?token=...`: verify JWT and execute simple actions (e.g., flip flag with percent)

- WebSocket
  - `/ws/audio`: gated by `VOICE_AVATAR_MVP`; streams STT→LLM→TTS→Avatar; emits one `turn` event with timing
    - Turn metrics recorded (ms): `stt_latency_ms`, `llm_first_token_ms`, `tts_synth_time_ms`, `total_turn_latency_ms`


### Background tasks

- Celery app: `apps.api.celery_app`
- Queues: `api, frontend, infra, etl`
- Tasks:
  - `apps.api.tasks.reports.generate_morning_brief`: daily artifact to MinIO
  - `apps.api.tasks.guardrails.canary_check`: rollback on guardrail breach
  - `apps.api.tasks.guardrails.canary_stepper`: escalates `VOICE_AVATAR_MVP` rollout 5%→25%→100% when guardrails OK; logs `canary.step` and `canary.rollback` events


### Database & migrations

- Alembic-first lifecycle: migrations are applied automatically at container startup (`alembic upgrade head`)
- Initial migration creates tables: `feature_flags, events, approvals, decisions, dlq`


### Local development

- See `docs/QUICKSTART.md` for Docker Compose commands, seeding, and example curls


