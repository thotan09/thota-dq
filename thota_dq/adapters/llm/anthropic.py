"""Anthropic LLM adapter using the anthropic SDK."""

from __future__ import annotations

import os

from anthropic import AsyncAnthropic

from .base import LLMAdapter


class AnthropicAdapter(LLMAdapter):
    """LLM adapter backed by Anthropic's API."""

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        api_key: str | None = None,
    ):
        self._model = model
        self._client = AsyncAnthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
        )

    async def complete(
        self, system: str, user: str, max_tokens: int = 1024
    ) -> tuple[str, int, int]:
        """Send a completion request and return (text, input_tokens, output_tokens)."""
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = msg.content[0].text if msg.content else ""
        return text, msg.usage.input_tokens, msg.usage.output_tokens
