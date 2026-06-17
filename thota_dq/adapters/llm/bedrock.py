"""AWS Bedrock LLM adapter — uses the Converse API (works with all Bedrock models).

Supports any model available in the account: Claude (when use-case form approved),
Amazon Nova, Mistral, etc.  Defaults to amazon.nova-pro-v1:0 which requires no
additional model-access request.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import boto3

from .base import LLMAdapter


class BedrockAdapter(LLMAdapter):
    """LLM adapter backed by AWS Bedrock Converse API.

    Args:
        model:   Bedrock model ID (defaults to amazon.nova-pro-v1:0).
                 For Claude: 'us.anthropic.claude-opus-4-5-20251101-v1:0'
                             'us.anthropic.claude-haiku-4-5-20251001-v1:0'
        profile: AWS profile name (reads ~/.aws/credentials).
        region:  AWS region (default us-east-1).
    """

    DEFAULT_MODEL = "amazon.nova-pro-v1:0"

    def __init__(
        self,
        model: str | None = None,
        profile: str | None = None,
        region: str = "us-east-1",
    ):
        self._model = model or self.DEFAULT_MODEL
        session = boto3.Session(profile_name=profile, region_name=region)
        self._client = session.client("bedrock-runtime", region_name=region)
        # Bounded executor prevents thread explosion under high concurrency
        self._executor = ThreadPoolExecutor(max_workers=8)

    async def complete(
        self, system: str, user: str, max_tokens: int = 1024
    ) -> tuple[str, int, int]:
        """Send a completion request; return (text, input_tokens, output_tokens)."""
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._invoke, system, user, max_tokens)

    def _invoke(self, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
        response = self._client.converse(
            modelId=self._model,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": max_tokens},
        )
        text = response["output"]["message"]["content"][0]["text"]
        usage = response.get("usage", {})
        in_tok = usage.get("inputTokens", 0)
        out_tok = usage.get("outputTokens", 0)
        return text, in_tok, out_tok
