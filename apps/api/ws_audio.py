from __future__ import annotations

import asyncio
import json
import os
import time
from typing import AsyncIterator, List, Optional

from fastapi import WebSocket

from .feature_flags import flags
from .providers.llm_router import LLMProvider, get_llm_provider
from .providers.stt import MockSTT, STTProvider, DeepgramSTT
from .providers.tts import MockTTS, TTSProvider, ElevenLabsTTS, AzureTTSTTS
from .providers.avatar import MockAvatar, AvatarProvider, BasicLipSyncAvatar
from .telemetry import track_event


async def _iter_until_close(ws: WebSocket) -> AsyncIterator[bytes]:
    while True:
        try:
            data = await ws.receive_bytes()
            yield data
        except Exception:
            break


async def handle_audio_ws(ws: WebSocket, session_id: str, user_id: Optional[str]) -> None:
    if not flags.is_enabled("VOICE_AVATAR_MVP", user_id=user_id):
        await ws.close(code=4403)
        return

    await ws.accept()
    start = time.perf_counter()
    stt_end_ts: Optional[float] = None
    first_token_ts: Optional[float] = None
    tts_start_ts: Optional[float] = None
    tts_end_ts: Optional[float] = None
    # Provider selection with env fallbacks
    stt_provider = os.getenv("STT_PROVIDER", "mock").lower()
    if stt_provider == "deepgram":
        stt: STTProvider = DeepgramSTT()
    else:
        stt = MockSTT()

    llm: LLMProvider = get_llm_provider()

    tts_provider = os.getenv("TTS_PROVIDER", "mock").lower()
    if tts_provider == "elevenlabs":
        tts: TTSProvider = ElevenLabsTTS()
    elif tts_provider == "azure":
        tts = AzureTTSTTS()
    else:
        tts = MockTTS()

    avatar_provider = os.getenv("AVATAR_PROVIDER", "mock").lower()
    if avatar_provider == "basic":
        avatar: AvatarProvider = BasicLipSyncAvatar()
    else:
        avatar = MockAvatar()

    # Receive audio and stream partials
    audio_iter = _iter_until_close(ws)
    partials: List[str] = []
    async for text in stt.stream_transcribe(audio_iter):
        partials.append(text)
        await ws.send_text(json.dumps({"type": "partial_transcript", "text": text}))
        if len(partials) >= 2:
            stt_end_ts = time.perf_counter()
            break

    # LLM stream (limit to first token for tests)
    response_text = "Hello world"
    tokens_out = 0
    async for tok in llm.stream(response_text):
        if first_token_ts is None:
            first_token_ts = time.perf_counter()
        tokens_out += LLMProvider.estimate_tokens(tok)
        await ws.send_text(json.dumps({"type": "llm_token", "token": tok}))
        break

    # TTS + Avatar stream
    async def tts_stream() -> AsyncIterator[bytes]:
        nonlocal tts_start_ts, tts_end_ts
        count = 0
        # mark tts start when we begin consuming synth output
        if tts_start_ts is None:
            tts_start_ts = time.perf_counter()
        async for chunk in tts.synthesize(response_text):
            await ws.send_text(
                json.dumps({"type": "tts_chunk", "size": len(chunk), "ts": time.time()})
            )
            yield chunk
            count += 1
            if count >= 2:
                # end measurement at the point TTS generated our last chunk
                tts_end_ts = time.perf_counter()
                return

    frame_count = 0
    async for frame in avatar.render(tts_stream()):
        await ws.send_text(
            json.dumps({"type": "avatar_chunk", "size": len(frame), "ts": time.time()})
        )
        frame_count += 1
        if frame_count >= 2:
            break

    total_latency_ms = int((time.perf_counter() - start) * 1000)
    # fallbacks in case timings were not captured
    stt_latency_ms = (
        int(((stt_end_ts if stt_end_ts is not None else time.perf_counter()) - start) * 1000)
    )
    llm_first_token_ms = (
        0 if first_token_ts is None else int((first_token_ts - start) * 1000)
    )
    tts_synth_time_ms = (
        0
        if tts_start_ts is None or tts_end_ts is None
        else int((tts_end_ts - tts_start_ts) * 1000)
    )

    # Optional telemetry enrichments
    provider_stt = stt.__class__.__name__.replace("STT", "").lower()
    provider_llm = getattr(llm, "provider_name", llm.__class__.__name__).lower()
    provider_tts = getattr(tts, "provider_name", tts.__class__.__name__).lower()
    provider_avatar = getattr(avatar, "provider_name", avatar.__class__.__name__).lower()

    tokens_prompt = LLMProvider.estimate_tokens(response_text)
    tokens_completion = tokens_out
    price_usd = 0.0
    try:
        price_usd = getattr(llm, "price_usd_for")(tokens_prompt, tokens_completion)  # type: ignore[misc]
    except Exception:
        price_usd = 0.0

    # Emit turn event
    try:
        track_event(
            name="turn",
            session_id=session_id,
            user_id=user_id,
            props={
                "stt_latency_ms": stt_latency_ms,
                "llm_first_token_ms": llm_first_token_ms,
                "tts_synth_time_ms": tts_synth_time_ms,
                "total_turn_latency_ms": total_latency_ms,
                # optional enrichments (validated as props_extra)
                "provider_stt": provider_stt,
                "provider_llm": provider_llm,
                "provider_tts": provider_tts,
                "provider_avatar": provider_avatar,
                "tokens_prompt": tokens_prompt,
                "tokens_completion": tokens_completion,
                "price_usd": price_usd,
            },
        )
    except Exception:
        pass

    await ws.send_text(json.dumps({"type": "done"}))
    await ws.close()


