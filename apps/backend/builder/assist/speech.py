"""Speech to text for the mic button on text fields.

Browsers that have their own speech recognition (Chrome, Edge, Safari) never
call this; the rest record a short clip and send it here. Groq's Whisper is
used when its key is set (fast, cheap, good with Hindi/Hinglish), else OpenAI's.
Both speak the same OpenAI-style ``/audio/transcriptions`` API.
"""
from __future__ import annotations

import os

import httpx

from builder.assist.llm import AssistUnavailable

MAX_AUDIO_BYTES = 10 * 1024 * 1024  # ~ several minutes of opus; the browser stops at 2 min


def _provider() -> tuple[str, str, str] | None:
    """(base_url, api_key, model) of the first configured speech provider."""
    groq = os.getenv("GROQ_API_KEY", "").strip()
    if groq:
        return (
            os.getenv("GROQ_BASE_URL", "").strip() or "https://api.groq.com/openai/v1",
            groq,
            os.getenv("GROQ_TRANSCRIBE_MODEL", "").strip() or "whisper-large-v3-turbo",
        )
    openai = os.getenv("OPENAI_API_KEY", "").strip()
    base = os.getenv("OPENAI_BASE_URL", "").strip()
    if openai and "azure.com" not in base:
        return (
            base or "https://api.openai.com/v1",
            openai,
            os.getenv("OPENAI_TRANSCRIBE_MODEL", "").strip() or "whisper-1",
        )
    return None


def available() -> bool:
    return _provider() is not None


async def transcribe(audio: bytes, filename: str, content_type: str, language: str | None = None) -> str:
    provider = _provider()
    if provider is None:
        raise AssistUnavailable("Voice typing isn't set up on this server (needs GROQ_API_KEY or OPENAI_API_KEY).")
    base_url, api_key, model = provider
    data = {"model": model, "response_format": "json"}
    if language:
        data["language"] = language
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{base_url.rstrip('/')}/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                data=data,
                files={"file": (filename, audio, content_type)},
            )
    except httpx.HTTPError as exc:
        raise AssistUnavailable(f"The speech service couldn't be reached: {exc}") from exc
    if r.status_code >= 400:
        raise AssistUnavailable(f"The speech service said no ({r.status_code}). Try again.")
    return str(r.json().get("text") or "").strip()
