"""Shared, lazily-constructed ``LLMGateway`` singleton.

Both embedding (``vendor.services.embedding.embed_text``) and chat
completion (``user.services.tool_call_planner.plan_tool_call``) need a
gateway instance; sharing one avoids spinning up a second set of provider
HTTP clients per process. Lives under ``vendor.services`` (not ``user``)
because ``vendor.services.embedding`` needs it and ``vendor`` must never
import from ``user`` — ``user.services.tool_call_planner`` importing this
one factory function back is a narrow, documented exception (see the
repo's import-linter contracts): it is a pure singleton getter with no
vendor business logic or data access.

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
