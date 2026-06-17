"""Tests for the Ollama LLM adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from thota_dq.adapters.llm.ollama import OllamaAdapter


def _mock_response(
    content: str,
    prompt_eval_count: int | None = 80,
    eval_count: int | None = 40,
    status_code: int = 200,
):
    """Build a mock httpx Response for the Ollama /api/chat endpoint."""
    body: dict = {"message": {"content": content}}
    if prompt_eval_count is not None:
        body["prompt_eval_count"] = prompt_eval_count
    if eval_count is not None:
        body["eval_count"] = eval_count

    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = body
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


@pytest.mark.asyncio
async def test_complete_returns_text_and_tokens():
    adapter = OllamaAdapter(model="llama3.2")
    mock_resp = _mock_response("Revenue looks negative.", prompt_eval_count=100, eval_count=30)

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
        text, in_tok, out_tok = await adapter.complete("system prompt", "user prompt")

    assert text == "Revenue looks negative."
    assert in_tok == 100
    assert out_tok == 30


@pytest.mark.asyncio
async def test_complete_missing_token_counts_defaults_to_zero():
    adapter = OllamaAdapter()
    mock_resp = _mock_response("Some text.", prompt_eval_count=None, eval_count=None)

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
        text, in_tok, out_tok = await adapter.complete("sys", "usr")

    assert text == "Some text."
    assert in_tok == 0
    assert out_tok == 0


@pytest.mark.asyncio
async def test_custom_model_and_base_url():
    adapter = OllamaAdapter(model="mistral", base_url="http://192.168.1.50:11434")
    mock_resp = _mock_response("ok", 10, 5)

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)) as mock_post:
        await adapter.complete("sys", "usr")

    call_args = mock_post.call_args
    url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", call_args.args[0])
    assert url == "http://192.168.1.50:11434/api/chat"
    payload = call_args.kwargs["json"]
    assert payload["model"] == "mistral"


@pytest.mark.asyncio
async def test_complete_raises_on_http_error():
    adapter = OllamaAdapter()
    mock_resp = _mock_response("", status_code=500)

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.complete("sys", "usr")


@pytest.mark.asyncio
async def test_max_tokens_passed_as_num_predict():
    adapter = OllamaAdapter(model="llama3.2")
    mock_resp = _mock_response("done", 20, 10)

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)) as mock_post:
        await adapter.complete("sys", "usr", max_tokens=512)

    payload = mock_post.call_args.kwargs["json"]
    assert payload["options"]["num_predict"] == 512


def test_default_attributes():
    adapter = OllamaAdapter()
    assert adapter._model == "llama3.2"
    assert adapter._base_url == "http://localhost:11434"
    assert adapter._timeout == 120.0


def test_adapter_satisfies_base_interface():
    from thota_dq.adapters.llm.base import LLMAdapter

    adapter = OllamaAdapter()
    assert isinstance(adapter, LLMAdapter)
    assert callable(adapter.complete)
