"""
Developer Integration Blueprint — LLM Gateway + Prompt Registry.
Location: apps/llm_gateway/tests/example_usage.py

Run directly:
    uv run python apps/llm_gateway/tests/example_usage.py
"""

import asyncio
from apps.llm_gateway.gateway import LLMGateway
from apps.llm_gateway.prompts import PromptRegistry, PromptType
from apps.llm_gateway.types import CompletionRequest, Message, Role


async def run_agentic_workflow_example():
    print("=================================================================")
    print("  Enterprise AI — LLM Gateway + Prompt Registry Integration")
    print("=================================================================")

    # -------------------------------------------------------------------------
    # STEP 1: Select and Format a System Prompt from PromptRegistry
    # -------------------------------------------------------------------------
    print("\n[STEP 1] Generating System Prompt using PromptRegistry...")
    
    system_prompt = PromptRegistry.format(
        PromptType.REACT_AGENT,
        agent_goal="Verify vendor invoice #INV-9021 and route for manager approval",
        bound_tools=["accounting.getInvoice", "approval.createTask"],
        knowledge_context="Policy: Invoices over $5,000 require CFO approval.",
        memory_context="Initial interaction — no previous attempts.",
    )
    print("✓ Rendered System Prompt successfully.")

    # -------------------------------------------------------------------------
    # STEP 2: Initialize Unified LLM Gateway
    # -------------------------------------------------------------------------
    print("\n[STEP 2] Initializing LLM Gateway...")
    gw = LLMGateway.from_env()
    print(f"✓ Gateway ready. Configured providers: {gw.configured_providers}")

    if not gw.configured_providers:
        print("⚠️ No API keys configured in .env! Set OPENAI_API_KEY, GROQ_API_KEY, or GEMINI_API_KEY.")
        return

    # -------------------------------------------------------------------------
    # STEP 3: Execute Prompt via Gateway (Swappable across OpenAI / Groq / Gemini)
    # -------------------------------------------------------------------------
    print("\n[STEP 3] Executing Agentic Prompt through Gateway...")

    request = CompletionRequest(
        messages=[
            Message(role=Role.SYSTEM, content=system_prompt),
            Message(role=Role.USER, content="Invoice #INV-9021 amount is $7,500. What is your next action?"),
        ],
        temperature=0.2,
    )

    try:
        # Pass active provider (e.g. groq or default)
        target_provider = "groq" if "groq" in gw.configured_providers else None
        response = await gw.complete(request, provider=target_provider)

        print(f"\nResponse from [{response.provider.upper()} / model: {response.model}]:")
        print("-----------------------------------------------------------------")
        print(response.content)
        print("-----------------------------------------------------------------")
        
        if response.reasoning:
            print(f"📌 [Backend Stored Reasoning Trace ({len(response.reasoning)} chars)]")

    except Exception as err:
        print(f"Execution Error: {err}")

    await gw.close()


if __name__ == "__main__":
    asyncio.run(run_agentic_workflow_example())
