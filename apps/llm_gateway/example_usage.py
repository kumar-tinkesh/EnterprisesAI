"""
Example usage of LLM Gateway.

Run directly:
    uv run python apps/llm_gateway/example_usage.py
"""

import asyncio
import os
from apps.llm_gateway.gateway import LLMGateway
from apps.llm_gateway.types import CompletionRequest, Message, Role


async def demo_direct_sdk():
    print("\n--- 1. Direct Gateway SDK Usage ---")
    
    # Initialize gateway from environment variables (OPENAI_API_KEY, GROQ_API_KEY, GEMINI_API_KEY)
    gw = LLMGateway.from_env()
    print(f"Configured Providers: {gw.configured_providers}")
    print(f"Default Provider: {gw.default_provider}")

    if not gw.configured_providers:
        print("⚠️ No API keys configured in environment! Set OPENAI_API_KEY, GROQ_API_KEY, or GEMINI_API_KEY.")
        return

    # Request completion (auto fallback enabled)
    req = CompletionRequest(
        messages=[
            Message(role=Role.SYSTEM, content="You are a helpful assistant."),
            Message(role=Role.USER, content="In 1 sentence, what is an Enterprise AI Gateway?"),
        ],
        temperature=0.3,
    )

    try:
        res = await gw.complete(req)
        print(f"\nResponse from [{res.provider} - {res.model}]:")
        print(res.content)
        print(f"Tokens used: {res.usage.total_tokens}")
    except Exception as e:
        print(f"Error during completion: {e}")

    await gw.close()


async def demo_streaming():
    print("\n--- 2. Streaming Response Demo ---")
    gw = LLMGateway.from_env()
    if not gw.configured_providers:
        return

    req = CompletionRequest(
        messages=[
            Message(role=Role.USER, content="Count from 1 to 5 with a short emoji per line."),
        ],
    )

    print("Streaming output: ", end="", flush=True)
    try:
        async for chunk in gw.stream(req):
            if chunk.content:
                print(chunk.content, end="", flush=True)
        print("\n[Stream Complete]")
    except Exception as e:
        print(f"Error during streaming: {e}")

    await gw.close()


async def main():
    await demo_direct_sdk()
    await demo_streaming()


if __name__ == "__main__":
    asyncio.run(main())
