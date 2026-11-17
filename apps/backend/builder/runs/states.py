"""Run, node-run, tool-call and approval states."""
from __future__ import annotations

QUEUED = "queued"
RUNNING = "running"
WAITING = "waiting"  # paused on a person; no worker holds it
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"

TERMINAL = frozenset({SUCCEEDED, FAILED, CANCELLED})
ACTIVE = frozenset({QUEUED, RUNNING, WAITING})

# Tool-call ledger.
CALL_AWAITING_APPROVAL = "awaiting_approval"
CALL_STARTED = "started"  # sent; if a run resumes and finds this, the outcome is unknown
CALL_SUCCEEDED = "succeeded"
CALL_FAILED = "failed"
CALL_DECLINED = "declined"
CALL_UNKNOWN = "unknown"  # connection broke mid-call: may or may not have run
CALL_DONE = frozenset({CALL_SUCCEEDED, CALL_FAILED, CALL_DECLINED})

# Approvals.
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
APPROVAL_EDITED = "edited"
APPROVAL_EXPIRED = "expired"
APPROVAL_YES = frozenset({APPROVAL_APPROVED, APPROVAL_EDITED})

KIND_TOOL_CALL = "tool_call"
KIND_UNCERTAIN_CALL = "uncertain_call"
KIND_HUMAN_STEP = "human_step"
# A workflow tool step whose required arguments weren't in the text.
KIND_MISSING_INPUT = "missing_input"
