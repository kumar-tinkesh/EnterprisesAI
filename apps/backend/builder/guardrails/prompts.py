"""Prompts for the model-judged guardrails and for suggesting guardrails.
Adapted from the AI Marketplace (prompts/guardrails.py, recommend_guardrails_prompt).
Wording is behaviour: change it deliberately.
"""
from __future__ import annotations


def groundedness_prompt(answer: str, evidence: list[str]) -> str:
    sources = "\n\n".join(f"- {e[:2000]}" for e in evidence)
    return f"""You are a strict fact-checker. Decide whether every factual claim in the ANSWER is supported by the SOURCES.

Rules:
- A claim is unsupported if the sources don't state it, or state something different (e.g. a different number, name, date or price).
- Do not use outside knowledge. Only the SOURCES count as truth.
- Ignore harmless filler ("hope this helps") and statements that the information isn't available.

SOURCES:
{sources}

ANSWER:
{answer}

Reply with ONLY compact JSON:
{{"supported": true|false, "unsupported_claims": ["..."], "reason": "one short sentence"}}"""


def custom_rules_prompt(rules: list[str], text: str) -> str:
    numbered = "\n".join(f"{i}. {r}" for i, r in enumerate(rules, start=1))
    return f"""Check the AI RESPONSE below against these rules it must follow. Report only clear violations —
a response that simply doesn't mention a topic does not violate a rule about it. Bracketed placeholders such
as [EMAIL], [PHONE], [CREDIT_CARD], [AADHAAR] or [PAN] mark personal details that were already removed: they
are not personal data and never a violation by themselves.

Rules:
{numbered}

AI RESPONSE:
{text[:12000]}

Reply with ONLY JSON: {{"violations": [{{"rule": <rule number>, "reason": "<one short sentence>"}}]}} — an empty
list if no rule is broken."""


def suggest_prompt(name: str, role: str, goal: str, instructions: str, tools: list[str], has_knowledge: bool) -> str:
    tool_list = ", ".join(tools) if tools else "none"
    return f"""An AI agent at a company is defined as:
Name: {name}
Role: {role}
Goal: {goal}
Instructions: {instructions or "(none)"}
Tools it can use: {tool_list}
Searches a knowledge base: {"yes" if has_knowledge else "no"}

Recommend which safety guardrails this agent needs, based on what it does and what could go wrong if it
misbehaves. Built-in guardrails (booleans):
- injection: refuse requests that try to override its instructions ("ignore previous instructions…").
  Worth it for almost any agent that takes free text from people.
- tool_injection: fence off instructions hidden in what its tools return (emails, web pages, documents,
  tickets written by outsiders). Turn on when a tool READS content other people wrote.
- pii_input: hide personal data (emails, phones, card/Aadhaar/PAN numbers) from the model. Only when the
  agent does NOT need those details to do its job (a summariser yes; an agent that emails customers no).
- pii_output: hide personal data in its answers. Only when its answers may reach people who shouldn't see it.
- groundedness: check answers against the knowledge base (only if it searches one); groundedness_mode "llm"
  for strict claim-by-claim checking where a wrong fact is costly (policy, finance, health), else "fast".

Also propose CUSTOM rules specific to this agent's job that the built-ins don't cover — short, concrete
sentences that can each be checked against a single answer ("Never quote a price that isn't in the price
list", "Never promise a refund; say a person will review it"). Cover what it must never disclose, never do
without confirmation, and when it must hand over to a person. 2-6 rules for an agent with real risk; zero if
it has none — don't invent rules to fill a number.

on_violation: "block" only where a broken rule could cause real harm (money, legal, health, sending messages
to customers); otherwise "flag".

Return ONLY JSON: {{"injection": bool, "tool_injection": bool, "pii_input": bool, "pii_output": bool,
"groundedness": bool, "groundedness_mode": "fast"|"llm", "custom_rules": ["..."], "on_violation": "flag"|"block",
"reasoning": "<one or two plain sentences for the agent's owner on why these — no setting names like tool_injection>"}}"""


__all__ = ["groundedness_prompt", "custom_rules_prompt", "suggest_prompt"]
