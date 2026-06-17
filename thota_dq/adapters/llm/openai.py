"""OpenAI LLM adapter using the openai SDK."""

from __future__ import annotations

import os

from openai import AsyncOpenAI

from .base import LLMAdapter


class OpenAIAdapter(LLMAdapter):
    """LLM adapter backed by OpenAI's API."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
    ):
        self._model = model
        self._client = AsyncOpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY")
        )

    async def complete(
        self, system: str, user: str, max_tokens: int = 1024
    ) -> tuple[str, int, int]:
        """Send a completion request and return (text, input_tokens, output_tokens)."""
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        return text, usage.prompt_tokens, usage.completion_tokens
