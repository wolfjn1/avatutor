from __future__ import annotations

import asyncio
import json
import math
import os
from typing import AsyncIterator, Dict, Optional, Tuple

import httpx


class LLMProvider:
    provider_name: str = "base"

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        raise NotImplementedError

    @staticmethod
    def estimate_tokens(text: str) -> int:
        # Cheap heuristic when tokenizer lib is unavailable
        return int(math.ceil(len(text) / 4)) if text else 0

    def price_usd_for(self, tokens_in: int, tokens_out: int) -> float:
        # Default: free
        return 0.0


class EchoLLM(LLMProvider):
    provider_name = "echo"

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        # Simple tokenization by words
        tokens = prompt.split()
        for tok in tokens:
            yield tok
            await asyncio.sleep(0.01)


class OpenAIChatLLM(LLMProvider):
    provider_name = "openai"

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        # price per 1k tokens (USD); defaults are conservative and can be overridden
        # Approx for gpt-4o-mini (as of mid-2024): $0.00015 in, $0.0006 out
        self.price_in_per_1k = float(os.getenv("OPENAI_PRICE_1K_PROMPT", "0.00015"))
        self.price_out_per_1k = float(os.getenv("OPENAI_PRICE_1K_COMPLETION", "0.0006"))

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        if not self.api_key:
            # Fallback to echo behavior if not configured
            async for tok in EchoLLM().stream(prompt):
                yield tok
            return

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, object] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "temperature": 0,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data = line[len("data: ") :].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except Exception:
                            continue
                        try:
                            delta = obj["choices"][0]["delta"]
                            content = delta.get("content")
                        except Exception:
                            content = None
                        if content:
                            yield str(content)

    def price_usd_for(self, tokens_in: int, tokens_out: int) -> float:
        return (tokens_in * self.price_in_per_1k + tokens_out * self.price_out_per_1k) / 1000.0


class AnthropicLLM(LLMProvider):
    provider_name = "anthropic"

    def __init__(self) -> None:
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku")
        # Approx for claude-3-haiku (as of mid-2024): $0.00025 in, $0.00125 out
        self.price_in_per_1k = float(os.getenv("ANTHROPIC_PRICE_1K_PROMPT", "0.00025"))
        self.price_out_per_1k = float(os.getenv("ANTHROPIC_PRICE_1K_COMPLETION", "0.00125"))

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        if not self.api_key:
            async for tok in EchoLLM().stream(prompt):
                yield tok
            return

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "content-type": "application/json",
            "anthropic-version": os.getenv("ANTHROPIC_VERSION", "2023-06-01"),
        }
        payload: Dict[str, object] = {
            "model": self.model,
            "max_tokens": 256,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data = line[len("data: ") :].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except Exception:
                            continue
                        # Anthropic streaming emits multiple event types; we want text deltas
                        if obj.get("type") == "content_block_delta":
                            delta = obj.get("delta") or {}
                            text = delta.get("text")
                            if text:
                                yield str(text)

    def price_usd_for(self, tokens_in: int, tokens_out: int) -> float:
        return (tokens_in * self.price_in_per_1k + tokens_out * self.price_out_per_1k) / 1000.0


def get_llm_provider() -> LLMProvider:
    provider = os.getenv("MODEL_PROVIDER", "echo").lower()
    if provider == "openai":
        return OpenAIChatLLM()
    if provider == "anthropic":
        return AnthropicLLM()
    # default and fallback
    return EchoLLM()


