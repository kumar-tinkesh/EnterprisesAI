"""Prompt-injection signatures (ported from the AI Marketplace, extended).

Pattern-based on purpose: fast, free, and explainable — we can say exactly
which phrase tripped it. It catches well-known phrasings; a determined attacker
can word around it, so it is defence in depth, not a guarantee. Used on the
request (block) and on tool results (fence off, since an email or web page a
tool fetched is a classic way to smuggle instructions to the model).
"""
from __future__ import annotations

import re

SIGNATURES: list[tuple[str, re.Pattern[str]]] = [
    ("instruction_override", re.compile(r"\bignore\s+(?:all\s+|any\s+)?(?:of\s+)?(?:the\s+|your\s+)?(?:previous|prior|above|earlier|preceding)\b.{0,20}\b(?:instructions?|prompts?|rules?|messages?)\b", re.I)),
    ("instruction_override", re.compile(r"\b(?:disregard|forget)\s+(?:all\s+|everything\s+|the\s+|your\s+)?(?:previous|prior|above|earlier|instructions|rules)\b", re.I)),
    ("instruction_override", re.compile(r"\bnew\s+(?:system\s+)?instructions?\s*:", re.I)),
    ("system_prompt_leak", re.compile(r"\b(?:reveal|show|print|repeat|output|tell\s+me)\b.{0,25}\b(?:system\s+prompt|initial\s+instructions|your\s+(?:instructions|prompt|rules))\b", re.I)),
    ("role_hijack", re.compile(r"\byou\s+are\s+now\s+(?:a|an|in|the|my)\b|\bact\s+as\s+(?:if\s+you\s+are\s+)?(?:a\s+)?(?:DAN|jailbroken|unrestricted|unfiltered)\b", re.I)),
    ("guardrail_bypass", re.compile(r"\b(?:developer|god|debug|jailbreak)\s+mode\b|\bwithout\s+any\s+(?:restrictions|filters|rules|limits)\b", re.I)),
    ("exfiltration", re.compile(r"\b(?:send|post|upload|email|forward)\b.{0,40}\b(?:to\s+https?://|to\s+my\s+(?:server|email|endpoint)|all\s+(?:the\s+)?(?:data|emails|files|contacts|credentials))\b", re.I)),
    ("hidden_markup", re.compile(r"<\s*/?\s*(?:system|im_start|im_end)\s*>|\[\s*/?INST\s*\]", re.I)),
]

LABELS = {
    "instruction_override": "tries to override the agent's instructions",
    "system_prompt_leak": "tries to read out the agent's instructions",
    "role_hijack": "tries to give the agent a new identity",
    "guardrail_bypass": "asks the agent to drop its safeguards",
    "exfiltration": "tries to send data somewhere",
    "hidden_markup": "contains hidden chat markup",
}


def detect(text: str) -> list[dict]:
    """[{type, match}] for each signature found (first match per signature type)."""
    if not text:
        return []
    found: dict[str, dict] = {}
    for label, pattern in SIGNATURES:
        if label in found:
            continue
        m = pattern.search(text)
        if m:
            found[label] = {"type": label, "match": m.group(0)[:80]}
    return list(found.values())


__all__ = ["detect", "LABELS"]
