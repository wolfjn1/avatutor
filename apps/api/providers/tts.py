from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator

import httpx


class TTSProvider:
    provider_name: str = "base"

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        raise NotImplementedError


class MockTTS(TTSProvider):
    provider_name = "mock"

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        # Chunk the text into pseudo audio frames
        for idx, chunk_start in enumerate(range(0, len(text), 5), start=1):
            chunk = text[chunk_start : chunk_start + 5].encode("utf-8")
            yield chunk
            await asyncio.sleep(0.01)


class ElevenLabsTTS(TTSProvider):
    provider_name = "elevenlabs"

    def __init__(self) -> None:
        self.api_key = os.getenv("ELEVEN_API_KEY", "")
        self.voice_id = os.getenv("ELEVEN_VOICE_ID", "")

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        if not self.api_key or not self.voice_id:
            async for chunk in MockTTS().synthesize(text):
                yield chunk
            return

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        headers = {"xi-api-key": self.api_key, "accept": "audio/mpeg"}
        payload = {"text": text, "voice_settings": {"stability": 0.5, "similarity_boost": 0.5}}
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            audio = resp.content
            # Chunk into small frames for smoother playback
            frame = 1024
            for i in range(0, len(audio), frame):
                yield audio[i : i + frame]
                await asyncio.sleep(0.005)


class AzureTTSTTS(TTSProvider):
    provider_name = "azure"

    def __init__(self) -> None:
        self.key = os.getenv("AZURE_TTS_KEY", "")
        self.region = os.getenv("AZURE_TTS_REGION", "")
        self.voice = os.getenv("AZURE_TTS_VOICE", "en-US-JennyNeural")

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        if not self.key or not self.region:
            async for chunk in MockTTS().synthesize(text):
                yield chunk
            return

        url = f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": self.key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-16khz-32kbitrate-mono-mp3",
        }
        ssml = (
            f"<speak version='1.0' xml:lang='en-US'><voice xml:lang='en-US' name='{self.voice}'>"
            f"{text}</voice></speak>"
        )
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.post(url, headers=headers, content=ssml)
            resp.raise_for_status()
            audio = resp.content
            frame = 1024
            for i in range(0, len(audio), frame):
                yield audio[i : i + frame]
                await asyncio.sleep(0.005)


