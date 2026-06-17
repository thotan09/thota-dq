"""Tests for the OpenAI LLM adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from thota_dq.adapters.llm.openai import OpenAIAdapter


def _mock_response(content: str, prompt_tokens: int = 80, completion_tokens: int = 40):
    """Build a mock openai ChatCompletion response."""
    choice = MagicMock()
    choice.message.content = content

    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


@pytest.mark.asyncio
async def test_complete_returns_text_and_tokens():
    adapter = OpenAIAdapter(model="gpt-4o-mini", api_key="sk-test")
    mock_resp = _mock_response("EXPLANATION: Revenue is negative.", 100, 30)

    with patch.object(
        adapter._client.chat.completions,
        "create",
        new=AsyncMock(return_value=mock_resp),
    ):
        text, in_tok, out_tok = await adapter.complete("system prompt", "user prompt")

    assert text == "EXPLANATION: Revenue is negative."
    assert in_tok == 100
    assert out_tok == 30


@pytest.mark.asyncio
async def test_complete_passes_system_and_user_as_messages():
    adapter = OpenAIAdapter(model="gpt-4o-mini", api_key="sk-test")
    mock_resp = _mock_response("ok", 10, 5)

    with patch.object(
        adapter._client.chat.completions,
        "create",
        new=AsyncMock(return_value=mock_resp),
    ) as mock_create:
        await adapter.complete("sys", "usr", max_tokens=256)

    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"
    assert call_kwargs["max_tokens"] == 256
    messages = call_kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "sys"}
    assert messages[1] == {"role": "user", "content": "usr"}


@pytest.mark.asyncio
async def test_empty_response_content():
    adapter = OpenAIAdapter(api_key="sk-test")
    mock_resp = _mock_response("", 10, 0)
    mock_resp.choices[0].message.content = None  # simulate null content

    with patch.object(
        adapter._client.chat.completions,
        "create",
        new=AsyncMock(return_value=mock_resp),
    ):
        text, _, _ = await adapter.complete("sys", "usr")

    assert text == ""


def test_default_model():
    adapter = OpenAIAdapter(api_key="sk-test")
    assert adapter._model == "gpt-4o-mini"


def test_custom_model():
    adapter = OpenAIAdapter(model="gpt-4o", api_key="sk-test")
    assert adapter._model == "gpt-4o"


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    adapter = OpenAIAdapter()
    # AsyncOpenAI reads the key — just confirm the adapter initialised
    assert adapter._model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_adapter_satisfies_base_interface():
    """OpenAIAdapter must satisfy the LLMAdapter contract."""
    from thota_dq.adapters.llm.base import LLMAdapter
    adapter = OpenAIAdapter(api_key="sk-test")
    assert isinstance(adapter, LLMAdapter)
    assert callable(adapter.complete)
