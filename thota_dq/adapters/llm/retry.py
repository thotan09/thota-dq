"""Retry wrapper for LLM adapters — exponential backoff on transient errors."""

from __future__ import annotations

import asyncio
import logging
import random

from .base import LLMAdapter

logger = logging.getLogger(__name__)

# Error substrings that indicate a transient / retriable condition
_RETRIABLE_PATTERNS = (
    "rate_limit",
    "ratelimit",
    "rate limit",
    "overloaded",
    "529",
    "503",
    "500",
    "timeout",
    "timed out",
    "connection",
    "temporarily",
    "too many requests",
    "capacity",
)


def _is_retriable(exc: BaseException) -> bool:
    """Return True if the exception looks like a transient API error."""
    text = f"{type(exc).__name__} {exc}".lower()
    return any(p in text for p in _RETRIABLE_PATTERNS)


class RetryingLLMAdapter(LLMAdapter):
    """Wraps any LLMAdapter and retries transient failures with exponential backoff.

    Args:
        inner: The underlying LLM adapter to wrap.
        max_attempts: Total attempts before giving up (default 3).
        base_delay: Initial backoff in seconds (doubles each attempt, default 1.0).
        max_delay: Cap on backoff delay in seconds (default 30.0).
    """

    def __init__(
        self,
        inner: LLMAdapter,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        self._inner = inner
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._max_delay = max_delay

    # Expose _model so pricing / audit logging works transparently
    @property
    def _model(self) -> str | None:
        return getattr(self._inner, "_model", None)

    async def complete(
        self, system: str, user: str, max_tokens: int = 1024
    ) -> tuple[str, int, int]:
        """Call inner.complete() with retry on transient errors."""
        last_exc: BaseException | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                return await self._inner.complete(system, user, max_tokens)
            except Exception as exc:
                if not _is_retriable(exc):
                    raise
                last_exc = exc
                if attempt == self._max_attempts:
                    break
                delay = min(
                    self._base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5),
                    self._max_delay,
                )
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt,
                    self._max_attempts,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        raise last_exc  # type: ignore[misc]
