"""Abstract base class for LLM adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMAdapter(ABC):
    """Abstract LLM adapter."""

    @abstractmethod
    async def complete(
        self, system: str, user: str, max_tokens: int = 1024
    ) -> tuple[str, int, int]:
        """Send a completion request.

        Returns:
            (text, input_tokens, output_tokens)
        """
        ...
