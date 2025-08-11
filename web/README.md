# Minimal Web Client

Run locally:

1. `npm install`
2. `npm run dev`

Notes:
- The client connects to `ws://localhost:8080/ws/audio?session_id=local&user_id=local-user`.
- Allow microphone permissions in the browser.
- Push-to-talk (spacebar) and VAD toggle are shown based on flags `PUSH_TO_TALK` and `VAD_BARGE_IN`.


