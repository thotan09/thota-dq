"""Per-model LLM pricing registry.

Prices are in USD per million tokens (input, output).
Looked up by model name prefix — longest match wins.
Falls back to Haiku pricing when a model is not found.
"""

from __future__ import annotations

# (input_price_per_M, output_price_per_M) in USD
_PRICING: dict[str, tuple[float, float]] = {
    # ── Anthropic Claude ──────────────────────────────────────────────
    "claude-haiku-4-5": (0.80, 4.00),
    "claude-haiku-3": (0.25, 1.25),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-3-7": (3.00, 15.00),
    "claude-sonnet-3-5": (3.00, 15.00),
    "claude-opus-4-7": (15.00, 75.00),
    "claude-opus-4": (15.00, 75.00),
    "claude-opus-3": (15.00, 75.00),
    # ── OpenAI ────────────────────────────────────────────────────────
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o1-mini": (3.00, 12.00),
    "o1": (15.00, 60.00),
    # ── AWS Bedrock Nova ──────────────────────────────────────────────
    "amazon.nova-pro": (0.80, 3.20),
    "amazon.nova-lite": (0.06, 0.24),
    "amazon.nova-micro": (0.035, 0.14),
    # ── AWS Bedrock Claude cross-region inference ─────────────────────
    "us.anthropic.claude-haiku-4-5": (0.80, 4.00),
    "us.anthropic.claude-sonnet-4": (3.00, 15.00),
    "us.anthropic.claude-opus-4": (15.00, 75.00),
    # ── Ollama (local — always free) ──────────────────────────────────
    "ollama/": (0.0, 0.0),
    "llama": (0.0, 0.0),
    "mistral": (0.0, 0.0),
    "mixtral": (0.0, 0.0),
    "phi": (0.0, 0.0),
    "gemma": (0.0, 0.0),
    "qwen": (0.0, 0.0),
}

# Fallback when no model matches (Haiku pricing is a safe conservative default)
_FALLBACK: tuple[float, float] = (0.80, 4.00)


def cost_usd(model: str | None, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for a given model and token counts.

    Args:
        model: Model identifier string (e.g. "claude-haiku-4-5-20251001").
               None or empty string falls back to default pricing.
        input_tokens: Number of input/prompt tokens.
        output_tokens: Number of output/completion tokens.

    Returns:
        Cost in USD as a float.
    """
    if not model:
        in_p, out_p = _FALLBACK
        return (input_tokens * in_p + output_tokens * out_p) / 1_000_000

    key = model.lower()

    # Exact match first
    if key in _PRICING:
        in_p, out_p = _PRICING[key]
        return (input_tokens * in_p + output_tokens * out_p) / 1_000_000

    # Prefix match — longest matching prefix wins
    best: tuple[float, float] | None = None
    best_len = 0
    for prefix, prices in _PRICING.items():
        if key.startswith(prefix) and len(prefix) > best_len:
            best = prices
            best_len = len(prefix)

    in_p, out_p = best if best is not None else _FALLBACK
    return (input_tokens * in_p + output_tokens * out_p) / 1_000_000
