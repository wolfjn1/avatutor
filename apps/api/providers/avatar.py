from __future__ import annotations

import asyncio
from typing import AsyncIterator


class AvatarProvider:
    provider_name: str = "base"

    async def render(self, audio_frames: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        raise NotImplementedError


class MockAvatar(AvatarProvider):
    provider_name = "mock"

    async def render(self, audio_frames: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        i = 0
        async for frame in audio_frames:
            i += 1
            yield b"frame-" + bytes(str(i), "utf-8") + b":" + frame[:4]
            await asyncio.sleep(0.005)


class BasicLipSyncAvatar(AvatarProvider):
    provider_name = "basic"

    async def render(self, audio_frames: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        # Map chunk cadence to simple mouth open/close frames
        open_frame = b"mouth:open"
        close_frame = b"mouth:close"
        open_next = True
        async for _ in audio_frames:
            yield open_frame if open_next else close_frame
            open_next = not open_next
            await asyncio.sleep(0.005)


