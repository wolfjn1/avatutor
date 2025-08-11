## Quickstart (Local Docker)

1) Copy env

```
cp .env.example .env
```

2) Bring up the stack (migrations run automatically)

```
docker compose -f infrastructure/docker-compose.yml up --build -d
```

3) Tail API logs

```
docker compose -f infrastructure/docker-compose.yml logs -f api
```

4) Seed default flags and admin approval key (after containers healthy)

```
docker compose -f infrastructure/docker-compose.yml exec api python scripts/seed.py
```

5) Try health

```
curl -s http://localhost:8080/health | jq .
```

6) Send a telemetry sample

```
curl -s -X POST http://localhost:8080/telemetry/track \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "session_started",
    "session_id": "s1",
    "user_id": "u1",
    "props": {"subject": "math", "entry_point": "quickstart"}
  }' | jq .
```

7) WS echo with websocat

```
brew install websocat # macOS
websocat -b ws://localhost:8080/ws/audio
# send two frames then flush
<Ctrl-]><Ctrl-]>
```

8) Run tests (inside API container)

```
docker compose -f infrastructure/docker-compose.yml exec api pytest -q

9) Ops CLI examples

```
docker compose -f infrastructure/docker-compose.yml exec api python opsctl/opsctl.py flags list
docker compose -f infrastructure/docker-compose.yml exec api python opsctl/opsctl.py approve mint DEC-123 --action flip_flag --flag VOICE_AVATAR_MVP --percent 5
```

### Providers (optional)

- Env-driven selection with safe mocks by default.
  - LLM: `MODEL_PROVIDER=openai|anthropic|echo` (default `echo`)
    - `OPENAI_API_KEY`, `OPENAI_MODEL` (e.g., `gpt-4o-mini`)
    - `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` (e.g., `claude-3-haiku`)
  - STT: `STT_PROVIDER=deepgram|mock` (default `mock`)
    - `DEEPGRAM_API_KEY`
  - TTS: `TTS_PROVIDER=elevenlabs|azure|mock` (default `mock`)
    - `ELEVEN_API_KEY`, `ELEVEN_VOICE_ID`
    - `AZURE_TTS_KEY`, `AZURE_TTS_REGION`, `AZURE_TTS_VOICE`
  - Avatar: `AVATAR_PROVIDER=basic|mock` (default `mock`)

All production calls are optional; if envs are not set, mocks are used. No new required analytics fields are introduced.

### Minimal Web client

- Navigate to `web/` and run:
  - `npm install`
  - `npm run dev`
- The client connects to `ws://localhost:8080/ws/audio?session_id=local&user_id=local-user`.
- Press and hold spacebar for push-to-talk if `PUSH_TO_TALK` is enabled; otherwise VAD toggle is shown when `VAD_BARGE_IN` is enabled.
- Grant mic permission in your browser.

```


