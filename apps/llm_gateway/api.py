"""
LLM Gateway — FastAPI service exposing the gateway over HTTP.

Endpoints
─────────
  GET  /health              → readiness check
  GET  /providers            → list configured providers
  GET  /models               → list models per provider
  POST /v1/chat/completions  → OpenAI-compatible completions (+ streaming SSE)
  POST /v1/embeddings        → OpenAI-compatible embeddings
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from apps.llm_gateway.gateway import LLMGateway
from apps.llm_gateway.exceptions import LLMGatewayError, ProviderNotConfiguredError
from apps.llm_gateway.types import (
    CompletionRequest,
    Message,
    Role,
    ToolDefinition,
)

logger = logging.getLogger("llm_gateway.api")

# ── singleton ────────────────────────────────────────────────────────────────

_gateway: Optional[LLMGateway] = None


def get_gateway() -> LLMGateway:
    assert _gateway is not None, "Gateway not initialised"
    return _gateway


# ── lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _gateway
    _gateway = LLMGateway.from_env()
    logger.info(
        "LLM Gateway started — providers: %s, default: %s",
        _gateway.configured_providers,
        _gateway.default_provider,
    )
    yield
    await _gateway.close()
    logger.info("LLM Gateway shut down.")


app = FastAPI(
    title="Enterprise AI — LLM Gateway",
    version="0.1.0",
    description="Unified, provider-agnostic LLM proxy for the Enterprise AI platform.",
    lifespan=lifespan,
)


# ── Pydantic request/response schemas ───────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None


class ToolFunctionDef(BaseModel):
    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolDef(BaseModel):
    type: str = "function"
    function: ToolFunctionDef


class ChatCompletionBody(BaseModel):
    model: Optional[str] = None
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    top_p: float = 1.0
    stop: Optional[list[str]] = None
    stream: bool = False
    tools: Optional[list[ToolDef]] = None
    tool_choice: Optional[str | dict[str, Any]] = None
    response_format: Optional[dict[str, Any]] = None


class EmbeddingBody(BaseModel):
    input: str | list[str]
    model: Optional[str] = None


# ── routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    gw = get_gateway()
    return {
        "status": "ok",
        "configured_providers": gw.configured_providers,
        "default_provider": gw.default_provider,
    }


@app.get("/providers")
async def providers():
    gw = get_gateway()
    return {"providers": gw.configured_providers, "default": gw.default_provider}


@app.get("/models")
async def models(provider: Optional[str] = None):
    gw = get_gateway()
    try:
        return await gw.list_models(provider)
    except LLMGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/v1/chat/completions")
async def chat_completions(
    body: ChatCompletionBody,
    x_llm_provider: Optional[str] = Header(None, alias="x-llm-provider"),
):
    """OpenAI-compatible chat completion endpoint."""
    gw = get_gateway()

    # Build the provider-agnostic request
    messages = [
        Message(
            role=Role(m.role),
            content=m.content,
            name=m.name,
            tool_call_id=m.tool_call_id,
        )
        for m in body.messages
    ]

    tools = None
    if body.tools:
        tools = [
            ToolDefinition(
                name=t.function.name,
                description=t.function.description,
                parameters=t.function.parameters,
            )
            for t in body.tools
        ]

    request = CompletionRequest(
        messages=messages,
        model=body.model,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        top_p=body.top_p,
        stop=body.stop,
        tools=tools,
        tool_choice=body.tool_choice,
        response_format=body.response_format,
        stream=body.stream,
    )

    provider = x_llm_provider

    try:
        if body.stream:
            return StreamingResponse(
                _stream_sse(gw, request, provider),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        resp = await gw.complete(request, provider=provider)
        return _format_completion_response(resp)

    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except LLMGatewayError as exc:
        status = exc.status_code or 502
        raise HTTPException(status_code=status, detail=str(exc))


@app.post("/v1/embeddings")
async def embeddings(
    body: EmbeddingBody,
    x_llm_provider: Optional[str] = Header(None, alias="x-llm-provider"),
):
    """OpenAI-compatible embeddings endpoint."""
    gw = get_gateway()
    texts = [body.input] if isinstance(body.input, str) else body.input
    try:
        resp = await gw.embed(texts, model=body.model, provider=x_llm_provider)
        return {
            "object": "list",
            "model": resp.model,
            "data": [
                {"object": "embedding", "index": i, "embedding": vec}
                for i, vec in enumerate(resp.embeddings)
            ],
            "usage": {
                "prompt_tokens": resp.usage.prompt_tokens,
                "total_tokens": resp.usage.total_tokens,
            },
        }
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except LLMGatewayError as exc:
        status = exc.status_code or 502
        raise HTTPException(status_code=status, detail=str(exc))


# ── helpers ──────────────────────────────────────────────────────────────────

def _format_completion_response(resp) -> dict:
    """Format to OpenAI-compatible JSON."""
    tool_calls = None
    if resp.tool_calls:
        tool_calls = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in resp.tool_calls
        ]

    message_dict: dict[str, Any] = {
        "role": "assistant",
        "content": resp.content,
    }
    if resp.reasoning:
        message_dict["reasoning"] = resp.reasoning
    if tool_calls:
        message_dict["tool_calls"] = tool_calls

    return {
        "id": "chatcmpl-gateway",
        "object": "chat.completion",
        "model": resp.model,
        "choices": [
            {
                "index": 0,
                "message": message_dict,
                "finish_reason": resp.finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        },
        "provider": resp.provider,
    }


async def _stream_sse(gw: LLMGateway, request, provider):
    """Yield Server-Sent Events for streaming responses."""
    try:
        async for chunk in gw.stream(request, provider=provider):
            data = {
                "id": "chatcmpl-gateway",
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": chunk.content} if chunk.content else {},
                        "finish_reason": chunk.finish_reason,
                    }
                ],
            }
            yield f"data: {json.dumps(data)}\n\n"
        yield "data: [DONE]\n\n"
    except LLMGatewayError as exc:
        error_data = {"error": {"message": str(exc), "provider": exc.provider}}
        yield f"data: {json.dumps(error_data)}\n\n"
