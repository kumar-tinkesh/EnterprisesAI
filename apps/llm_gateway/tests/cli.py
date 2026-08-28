"""
CLI Test Script for LLM Gateway & Prompt Registry (apps/llm_gateway/tests/cli.py).

Run directly:
    uv run python apps/llm_gateway/tests/cli.py
"""

import asyncio
from apps.llm_gateway.gateway import LLMGateway
from apps.llm_gateway.prompts import PromptRegistry, PromptType
from apps.llm_gateway.types import CompletionRequest, Message, Role


# =============================================================================
# PART 1: KAISE PROMPT BANATE HAIN (PromptRegistry Usage)
# =============================================================================
def test_prompt_registry():
    print("\n=================================================================")
    print("  PART 1: PROMPT BUILDER DEMO (PromptRegistry)")
    print("=================================================================")

    print("\n--- Available System Prompts in Registry ---")
    for name in PromptRegistry.list_prompts():
        print(f"  • {name}")

    print("\n--- Example 1: Creating a ReAct Agent System Prompt ---")
    react_prompt = PromptRegistry.format(
        PromptType.REACT_AGENT,
        agent_goal="Process vendor invoice #INV-9021",
        bound_tools=["accounting.getInvoice", "approval.createTask"],
        knowledge_context="Policy: Invoices > $5,000 require CFO approval",
        memory_context="No previous interaction",
    )
    print(react_prompt)

    print("\n--- Example 2: Creating an AI Designer System Prompt ---")
    designer_prompt = PromptRegistry.format(
        PromptType.AI_DESIGNER,
        available_tools=["slack.sendMessage", "hris.createEmployee"],
        available_knowledge=["HR Onboarding Handbook 2025"],
    )
    print(designer_prompt[:350] + "\n... [truncated] ...")


# =============================================================================
# PART 2: KAISE LLM GATEWAY USE KARTE HAIN (LLMGateway Usage)
# =============================================================================
async def test_llm_gateway_basics():
    print("\n=================================================================")
    print("  PART 2: LLM GATEWAY DEMO (Direct Provider Calls & Streaming)")
    print("=================================================================")

    gw = LLMGateway.from_env()
    print(f"✓ Configured Providers: {gw.configured_providers}")
    print(f"✓ Default Provider: {gw.default_provider}")

    if not gw.configured_providers:
        print("\n⚠️ No API keys found in .env! Set OPENAI_API_KEY, GROQ_API_KEY, or GEMINI_API_KEY.")
        return

    # Select active provider (prefer groq or default)
    target_provider = "groq" if "groq" in gw.configured_providers else gw.default_provider

    # A. Chat Completion
    print(f"\n--- A. Chat Completion via [{target_provider.upper()}] ---")
    try:
        response = await gw.complete(
            CompletionRequest(
                messages=[Message(role=Role.USER, content="Hello LLM Gateway!")],
                temperature=0.3,
            ),
            provider=target_provider,
        )
        print(f"Response [{response.provider} / {response.model}]:")
        print(response.content)
        if response.reasoning:
            print(f"📌 [Backend Stored Reasoning ({len(response.reasoning)} chars)]")
    except Exception as e:
        print(f"Error: {e}")

    # B. Streaming
    print(f"\n--- B. Streaming Tokens via [{target_provider.upper()}] ---")
    try:
        print("Stream output: ", end="", flush=True)
        async for chunk in gw.stream(
            CompletionRequest(messages=[Message(role=Role.USER, content="Count to 5")]),
            provider=target_provider,
        ):
            if chunk.content:
                print(chunk.content, end="", flush=True)
        print("\n[Stream Complete]")
    except Exception as e:
        print(f"\nStream Error: {e}")

    # C. Embeddings
    print("\n--- C. Text Embeddings ---")
    try:
        emb = await gw.embed(["Enterprise AI vector test"])
        print(f"[{emb.provider} / {emb.model}] Vector dimension: {len(emb.embeddings[0])}")
    except Exception as e:
        print(f"Embedding Error (or provider skipped): {e}")

    await gw.close()


# =============================================================================
# PART 3: PROMPT + LLM GATEWAY TOGETHER (Agentic Execution)
# =============================================================================
async def test_agentic_workflow_integration():
    print("\n=================================================================")
    print("  PART 3: PROMPT REGISTRY + LLM GATEWAY INTEGRATION")
    print("=================================================================")

    # 1. Build System Prompt
    system_prompt = PromptRegistry.format(
        PromptType.REACT_AGENT,
        agent_goal="Route invoice approval task",
        bound_tools=["approval.createTask"],
        knowledge_context="Policy: Over $5k needs CFO approval",
        memory_context="Initial run",
    )

    # 2. Run via Gateway
    gw = LLMGateway.from_env()
    if not gw.configured_providers:
        return

    target_provider = "groq" if "groq" in gw.configured_providers else gw.default_provider

    try:
        response = await gw.complete(
            CompletionRequest(
                messages=[
                    Message(role=Role.SYSTEM, content=system_prompt),
                    Message(role=Role.USER, content="Invoice #INV-100 is $8,000. What is your action?"),
                ]
            ),
            provider=target_provider,
        )
        print(f"Agent Action [{response.provider} / {response.model}]:")
        print(response.content)
    except Exception as e:
        print(f"Agentic Execution Error: {e}")

    await gw.close()


# =============================================================================
# MAIN RUNNER
# =============================================================================
async def main():
    # 1. Show Prompt Creation
    test_prompt_registry()

    # 2. Show LLM Gateway Basics
    await test_llm_gateway_basics()

    # 3. Show Agentic Integration (Prompt + Gateway)
    await test_agentic_workflow_integration()


if __name__ == "__main__":
    asyncio.run(main())
