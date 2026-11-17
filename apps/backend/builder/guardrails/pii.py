"""Personal data: find it and redact it (regex, local).

Ported from the AI Marketplace and extended with Indian identifiers (Aadhaar,
PAN, +91 mobiles). Deliberately conservative and explainable — no model and no
network call, so it can't leak the data it protects. It catches the common
high-risk formats; it is not a complete DLP system.
"""
from __future__ import annotations

import re

# Order matters: the specific patterns run before the looser ones, and a span
# claimed by one is not matched again.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("API_KEY", re.compile(r"\b(?:sk|pk|rk|ghp|gho|xox[abp]|AIza)[-_A-Za-z0-9]{16,}\b")),
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    # Not part of a longer run of digit groups (an order or account number).
    ("AADHAAR", re.compile(r"(?<!\d)(?<!\d[ -])[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?![ -]?\d)")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("IP_ADDRESS", re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")),
    ("PHONE", re.compile(r"(?<![\w+])(?:\+91[ -]?)?[6-9]\d{4}[ -]?\d{5}\b")),
    ("PHONE", re.compile(r"(?<![\w+])(?:\+?\d{1,3}[ -]?)?(?:\(\d{3}\)|\d{3})[ -]?\d{3}[ -]?\d{4}\b")),
]


def _valid(label: str, value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if label == "CREDIT_CARD":
        return 13 <= len(digits) <= 19 and _luhn(digits)
    return True


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def scan(text: str) -> list[dict]:
    """[{type, start, end}] for every personal detail found (values are never returned)."""
    if not text:
        return []
    taken: list[tuple[int, int]] = []
    hits: list[dict] = []
    for label, pattern in PATTERNS:
        for m in pattern.finditer(text):
            start, end = m.span()
            if any(start < e and s < end for s, e in taken) or not _valid(label, m.group(0)):
                continue
            taken.append((start, end))
            hits.append({"type": label, "start": start, "end": end})
    return sorted(hits, key=lambda h: h["start"])


def redact(text: str) -> tuple[str, list[str]]:
    """Replace each personal detail with [<TYPE>] -> (clean text, the types found, in order)."""
    hits = scan(text)
    if not hits:
        return text, []
    out, cursor = [], 0
    for h in hits:
        out.append(text[cursor:h["start"]])
        out.append(f"[{h['type']}]")
        cursor = h["end"]
    out.append(text[cursor:])
    return "".join(out), [h["type"] for h in hits]


def describe(types: list[str]) -> str:
    """["EMAIL", "EMAIL", "PHONE"] -> "2 emails, 1 phone number"."""
    names = {
        "EMAIL": ("email", "emails"), "PHONE": ("phone number", "phone numbers"), "CREDIT_CARD": ("card number", "card numbers"),
        "AADHAAR": ("Aadhaar number", "Aadhaar numbers"), "PAN": ("PAN", "PANs"), "SSN": ("SSN", "SSNs"),
        "IP_ADDRESS": ("IP address", "IP addresses"), "API_KEY": ("API key", "API keys"),
    }
    counts: dict[str, int] = {}
    for t in types:
        counts[t] = counts.get(t, 0) + 1
    return ", ".join(f"{n} {names.get(t, (t.lower(), t.lower()))[0 if n == 1 else 1]}" for t, n in counts.items())


__all__ = ["scan", "redact", "describe"]
