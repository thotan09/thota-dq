"""Tests for RetryingLLMAdapter — exponential backoff on transient errors."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thota_dq.adapters.llm.retry import RetryingLLMAdapter, _is_retriable

# ── _is_retriable helpers ────────────────────────────────────────────────────


class _Err(Exception):
    pass


def test_rate_limit_is_retriable():
    assert _is_retriable(_Err("rate_limit exceeded"))
    assert _is_retriable(_Err("RateLimitError: too many requests"))


def test_overloaded_is_retriable():
    assert _is_retriable(_Err("API overloaded"))


def test_timeout_is_retriable():
    assert _is_retriable(_Err("Request timed out"))
    assert _is_retriable(_Err("timeout waiting for response"))


def test_500_is_retriable():
    assert _is_retriable(_Err("HTTP 500 Internal Server Error"))


def test_503_is_retriable():
    assert _is_retriable(_Err("503 Service Unavailable"))


def test_connection_is_retriable():
    assert _is_retriable(ConnectionError("connection refused"))


def test_value_error_not_retriable():
    assert not _is_retriable(ValueError("bad model name"))


def test_auth_error_not_retriable():
    assert not _is_retriable(_Err("AuthenticationError: invalid key"))


# ── RetryingLLMAdapter ───────────────────────────────────────────────────────


@pytest.fixture
def inner():
    m = MagicMock()
    m._model = "claude-haiku-4-5-20251001"
    return m


@pytest.mark.asyncio
async def test_success_on_first_attempt(inner):
    inner.complete = AsyncMock(return_value=("hello", 10, 5))
    adapter = RetryingLLMAdapter(inner, max_attempts=3)
    result = await adapter.complete("sys", "usr")
    assert result == ("hello", 10, 5)
    assert inner.complete.call_count == 1


@pytest.mark.asyncio
async def test_retries_on_transient_error(inner):
    inner.complete = AsyncMock(side_effect=[_Err("rate_limit"), ("ok", 20, 8)])
    adapter = RetryingLLMAdapter(inner, max_attempts=3, base_delay=0.0)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await adapter.complete("sys", "usr")
    assert result == ("ok", 20, 8)
    assert inner.complete.call_count == 2


@pytest.mark.asyncio
async def test_raises_after_max_attempts(inner):
    inner.complete = AsyncMock(side_effect=_Err("503 overloaded"))
    adapter = RetryingLLMAdapter(inner, max_attempts=3, base_delay=0.0)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(_Err, match="503 overloaded"):
            await adapter.complete("sys", "usr")
    assert inner.complete.call_count == 3


@pytest.mark.asyncio
async def test_non_retriable_error_raised_immediately(inner):
    inner.complete = AsyncMock(side_effect=ValueError("invalid param"))
    adapter = RetryingLLMAdapter(inner, max_attempts=3, base_delay=0.0)
    with pytest.raises(ValueError, match="invalid param"):
        await adapter.complete("sys", "usr")
    assert inner.complete.call_count == 1


@pytest.mark.asyncio
async def test_model_property_proxied(inner):
    inner._model = "gpt-4o"
    adapter = RetryingLLMAdapter(inner)
    assert adapter._model == "gpt-4o"


@pytest.mark.asyncio
async def test_model_property_none_when_inner_lacks_it():
    inner = MagicMock(spec=[])  # no _model attribute
    inner.complete = AsyncMock(return_value=("x", 1, 1))
    adapter = RetryingLLMAdapter(inner)
    assert adapter._model is None
    result = await adapter.complete("s", "u")
    assert result == ("x", 1, 1)


@pytest.mark.asyncio
async def test_sleep_delay_called_between_retries(inner):
    inner.complete = AsyncMock(side_effect=[_Err("overloaded"), _Err("overloaded"), ("done", 5, 5)])
    adapter = RetryingLLMAdapter(inner, max_attempts=3, base_delay=1.0, max_delay=30.0)
    sleep_calls = []

    async def fake_sleep(delay):
        sleep_calls.append(delay)

    with patch("asyncio.sleep", side_effect=fake_sleep):
        result = await adapter.complete("sys", "usr")

    assert result == ("done", 5, 5)
    assert len(sleep_calls) == 2
    # First delay ≈ 1.0s (base), second ≈ 2.0s; with jitter both > 0
    assert sleep_calls[0] > 0
    assert sleep_calls[1] > sleep_calls[0]


@pytest.mark.asyncio
async def test_delay_capped_at_max_delay(inner):
    inner.complete = AsyncMock(side_effect=[_Err("rate_limit"), ("ok", 1, 1)])
    adapter = RetryingLLMAdapter(inner, max_attempts=2, base_delay=100.0, max_delay=5.0)
    sleep_calls = []

    async def fake_sleep(delay):
        sleep_calls.append(delay)

    with patch("asyncio.sleep", side_effect=fake_sleep):
        await adapter.complete("sys", "usr")

    assert sleep_calls[0] <= 5.0
