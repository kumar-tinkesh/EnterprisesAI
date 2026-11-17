"""Model calls for the builder assistant (through the LLM gateway)."""
from __future__ import annotations

import json
import logging

from builder.workflows.text import strip_json_fence

logger = logging.getLogger("builder.assist")


class AssistUnavailable(Exception):
    """The model couldn't be reached or kept answering with something unusable."""


class Usage:
    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def add(self, response) -> None:
        self.prompt_tokens += response.usage.prompt_tokens or 0
        self.completion_tokens += response.usage.completion_tokens or 0


async def ask(prompt: str, usage: Usage, *, json_mode: bool, max_tokens: int = 3000, temperature: float = 0.2) -> str:
    from apps.llm_gateway.types import CompletionRequest, Message, Role

    from builder.agents import runtime

    request = CompletionRequest(
        messages=[Message(role=Role.USER, content=prompt)],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"} if json_mode else None,
    )
    try:
        response = await runtime._gateway().complete(request)
    except Exception as exc:  # noqa: BLE001 — surfaced as one clear error
        raise AssistUnavailable(f"The AI model isn't available right now: {exc}") from exc
    usage.add(response)
    return response.content or ""


async def ask_json(prompt: str, usage: Usage, *, max_tokens: int = 3000) -> dict:
    """One JSON object; asks once more if the first answer doesn't parse."""
    raw = ""
    for attempt in range(2):
        raw = await ask(
            prompt if attempt == 0 else f"{prompt}\n\nYour previous answer was not valid JSON. Return ONLY the JSON object.",
            usage, json_mode=True, max_tokens=max_tokens,
        )
        try:
            value = json.loads(strip_json_fence(raw))
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    logger.warning("assistant returned unusable JSON: %r", raw[:300])
    raise AssistUnavailable("The AI model didn't return a usable answer. Try again or rephrase.")
