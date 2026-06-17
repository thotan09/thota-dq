"""Ollama LLM adapter using httpx to call a local Ollama instance."""

from __future__ import annotations

import httpx

from .base import LLMAdapter


class OllamaAdapter(LLMAdapter):
    """LLM adapter backed by a local Ollama instance."""

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
        timeout: float = 120.0,
    ):
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def complete(
        self, system: str, user: str, max_tokens: int = 1024
    ) -> tuple[str, int, int]:
        """Send a completion request and return (text, input_tokens, output_tokens)."""
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()

        data = resp.json()
        text = data.get("message", {}).get("content", "")
        input_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)
        return text, input_tokens, output_tokens
