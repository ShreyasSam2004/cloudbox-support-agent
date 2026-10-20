"""Model pricing used for cost *estimates* (USD per million tokens).

Anthropic prices are first-party API list prices as of 2026-10. OpenAI entries are indicative and
should be verified against the provider's current price list before relying on them; override any
entry at runtime with ``MODEL_PRICING_JSON='{"model": [in, out, cache_read, cache_write]}'``.
Local (Ollama) models cost nothing per token.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_write_per_mtok: float


_DEFAULT_PRICES: dict[str, ModelPrice] = {
    # Anthropic (cache write = 1.25x input for the 5-minute TTL)
    "claude-opus-5-5": ModelPrice(4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": ModelPrice(2.00, 10.00, 0.20, 2.50),
    "claude-haiku-5-5": ModelPrice(0.10, 0.50, 0.01, 0.125),
    "claude-opus-5": ModelPrice(5.00, 25.00, 0.50, 6.25),
    "claude-sonnet-5": ModelPrice(2.00, 10.00, 0.20, 2.50),
    # OpenAI (indicative)
    "gpt-4.1": ModelPrice(2.00, 8.00, 0.50, 2.00),
    "gpt-4.1-mini": ModelPrice(0.40, 1.60, 0.10, 0.40),
    "gpt-4o-mini": ModelPrice(0.15, 0.60, 0.075, 0.15),
}

_FREE = ModelPrice(0.0, 0.0, 0.0, 0.0)


def _load_overrides() -> dict[str, ModelPrice]:
    raw = os.environ.get("MODEL_PRICING_JSON")
    if not raw:
        return {}
    parsed = json.loads(raw)
    return {name: ModelPrice(*map(float, values)) for name, values in parsed.items()}


def price_for(provider: str, model: str) -> ModelPrice | None:
    """Return the price for ``model`` or ``None`` when unknown (cost then reported as unknown)."""
    if provider in ("ollama", "scripted"):
        return _FREE
    overrides = _load_overrides()
    if model in overrides:
        return overrides[model]
    return _DEFAULT_PRICES.get(model)


def estimate_cost_usd(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float | None:
    price = price_for(provider, model)
    if price is None:
        return None
    return (
        input_tokens * price.input_per_mtok
        + output_tokens * price.output_per_mtok
        + cache_read_tokens * price.cache_read_per_mtok
        + cache_write_tokens * price.cache_write_per_mtok
    ) / 1_000_000
