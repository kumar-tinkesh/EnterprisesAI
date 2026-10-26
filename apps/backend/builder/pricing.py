"""What a run cost, estimated from its token counts.

Ported from the AI Marketplace's ``core/utils/pricing.py`` (USD per 1K
tokens, input / output). Providers report dated or prefixed model names
("azure/gpt-4o-2024-08-06"), so a model matches the longest known name it
starts with once any ``provider/`` prefix is dropped. An unknown model has no
estimate (None) rather than a guessed one.
"""
from __future__ import annotations

PRICING_PER_1K: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4.1": (0.002, 0.008),
    "gpt-4.1-mini": (0.0004, 0.0016),
    "gpt-4.1-nano": (0.0001, 0.0004),
    "gpt-5": (0.00125, 0.01),
    "gpt-5-mini": (0.00025, 0.002),
    "gpt-5-nano": (0.00005, 0.0004),
    "o4-mini": (0.0011, 0.0044),
    "claude-opus-5": (0.005, 0.025),
    "claude-sonnet-5": (0.003, 0.015),
    "claude-haiku-4-5": (0.001, 0.005),
    "gemini-2.5-pro": (0.00125, 0.01),
    "gemini-2.5-flash": (0.0003, 0.0025),
    "gemini-2.5-flash-lite": (0.0001, 0.0004),
    "gemini-flash-lite-latest": (0.0001, 0.0004),
    "llama-3.3-70b-versatile": (0.00059, 0.00079),
    "llama-3.1-8b-instant": (0.00005, 0.00008),
}


def rates_for(model: str | None) -> tuple[float, float] | None:
    name = (model or "").strip().lower().rsplit("/", 1)[-1]
    if not name:
        return None
    if name in PRICING_PER_1K:
        return PRICING_PER_1K[name]
    known = [k for k in PRICING_PER_1K if name.startswith(k)]
    return PRICING_PER_1K[max(known, key=len)] if known else None


def estimate_cost_usd(model: str | None, prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
    rates = rates_for(model)
    if rates is None or prompt_tokens is None or completion_tokens is None:
        return None
    in_rate, out_rate = rates
    return round(prompt_tokens / 1000 * in_rate + completion_tokens / 1000 * out_rate, 6)


def add_cost(total: float | None, more: float | None) -> float | None:
    """Sum two estimates; None (unknown) only when both are."""
    if total is None and more is None:
        return None
    return round((total or 0.0) + (more or 0.0), 6)


__all__ = ["PRICING_PER_1K", "add_cost", "estimate_cost_usd", "rates_for"]
