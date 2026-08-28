"""
CLI Test script for LLM Gateway (apps/llm_gateway/cli.py).

Run with:
    uv run python apps/llm_gateway/cli.py
"""

import asyncio
from apps.llm_gateway.gateway import LLMGateway
from apps.llm_gateway.types import CompletionRequest, Message, Role


async def main():
    # Automatically reads OPENAI_API_KEY, GROQ_API_KEY, GEMINI_API_KEY from environment
    gw = LLMGateway.from_env()
    print(f"Configured Providers: {gw.configured_providers}")
    print(f"Default Provider: {gw.default_provider}")

    if not gw.configured_providers:
        print("\n⚠️ No API keys configured in environment!")
        print("Please set OPENAI_API_KEY, GROQ_API_KEY, or GEMINI_API_KEY in your .env file.")
        return

    # 1. Chat Completion (auto fallback enabled by default)
    print("\n--- 1. Testing Chat Completion ---")
    try:
        response = await gw.complete(
            CompletionRequest(
                messages=[
                    Message(role=Role.SYSTEM, content="You are an enterprise AI assistant."),
                    Message(role=Role.USER, content="Summarize the purpose of an LLM gateway in 1 sentence."),
                ],
                temperature=0.3,
            )
        )
        print(f"[{response.provider} / {response.model}]: {response.content}")
        print(f"Total tokens: {response.usage.total_tokens}")
    except Exception as e:
        print(f"Error in chat completion: {e}")

    # 2. Force a specific provider if configured (e.g. Groq for ultra-low latency)
    print("\n--- 2. Testing Specific Provider (Groq) ---")
    if "groq" in gw.configured_providers:
        try:
            groq_resp = await gw.complete(
                CompletionRequest(messages=[Message(role=Role.USER, content="Hello Groq")]),
                provider="groq",
            )
            print(f"[{groq_resp.provider} / {groq_resp.model}]: {groq_resp.content}")
        except Exception as e:
            print(f"Error calling Groq: {e}")
    else:
        print("Skipped Groq test (GROQ_API_KEY not set)")

    # 3. Stream output
    print("\n--- 3. Testing Streaming Output ---")
    try:
        print("Streaming output: ", end="", flush=True)
        async for chunk in gw.stream(
            CompletionRequest(messages=[Message(role=Role.USER, content="Count to 5")])
        ):
            if chunk.content:
                print(chunk.content, end="", flush=True)
        print("\n[Stream Complete]")
    except Exception as e:
        print(f"\nError during streaming: {e}")

    # 4. Embeddings
    print("\n--- 4. Testing Embeddings ---")
    try:
        emb = await gw.embed(["enterprise context vector"])
        print(f"[{emb.provider} / {emb.model}] Embedding vector length: {len(emb.embeddings[0])}")
    except Exception as e:
        print(f"Error in embedding generation: {e}")

    await gw.close()


if __name__ == "__main__":
    asyncio.run(main())
