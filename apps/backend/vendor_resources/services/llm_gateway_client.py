"""Shared, lazily-constructed ``LLMGateway`` singleton for vendor_resources.

Both embedding (``catalog_engine.embed_text``) and chat completion
(``tool_call_planner.plan_tool_call``) need a gateway instance; sharing one
avoids spinning up a second set of provider HTTP clients per process.

Import is deferred inside the function (not at module load) so a missing
``apps.llm_gateway`` dependency or bad env config doesn't crash this module
at import time — every caller here already treats a gateway failure as
"feature unavailable right now", not fatal.
"""
from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.llm_gateway.gateway import LLMGateway


@lru_cache
def get_gateway() -> "LLMGateway":
    from apps.llm_gateway.gateway import LLMGateway

    return LLMGateway.from_env()
