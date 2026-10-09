"""Builder runtime settings, read from the environment / ``.env``."""
from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class BuilderSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Default per-call timeout; a caller may ask for less, never more than the max.
    TOOL_CALL_TIMEOUT_SECONDS: float = 60.0
    TOOL_CALL_MAX_TIMEOUT_SECONDS: float = 600.0
    # Starting a session (spawning a stdio server, which may first npm/uv
    # install it, then the MCP initialize handshake).
    TOOL_SESSION_CONNECT_TIMEOUT_SECONDS: float = 120.0
    # A pooled session unused this long is closed (its process stopped).
    TOOL_SESSION_IDLE_SECONDS: float = 300.0
    TOOL_SESSION_MAX_OPEN: int = 64
    TOOL_SESSION_MAX_PER_USER: int = 8
    # Text returned to the caller (and later the LLM) is capped at this many characters.
    TOOL_RESULT_MAX_CHARS: int = 100_000

    # Each user's stdio servers run with HOME under here (0700), so one
    # user's OAuth/credential files are never visible to another's process.
    BUILDER_USER_HOME_ROOT: str = str(Path(tempfile.gettempdir()) / "enterpriseai-mcp-home")

    # ── Runs ──
    # "inline": the API process runs the worker itself (local dev, one process).
    # "redis":  runs are queued on Redis Streams and executed by separate
    #           `python -m builder.worker` processes; events go over Redis pub/sub.
    BUILDER_QUEUE_BACKEND: str = "inline"
    REDIS_URL: str = "redis://localhost:6379/0"
    BUILDER_RUN_STREAM: str = "builder:runs"
    BUILDER_RUN_GROUP: str = "builder-workers"
    WORKER_CONCURRENCY: int = 4
    # A worker holds a run by renewing a lease; if it dies, the lease lapses
    # and another worker resumes the run from its last checkpoint.
    RUN_LEASE_SECONDS: float = 60.0
    RUN_HEARTBEAT_SECONDS: float = 15.0
    # How often lapsed leases and runs lost from the queue are re-enqueued.
    RUN_REAPER_INTERVAL_SECONDS: float = 30.0
    # A queued run nobody picked up for this long is re-enqueued (e.g. Redis restarted).
    RUN_REQUEUE_AFTER_SECONDS: float = 120.0
    # Times a run may be picked up again after its worker died, before it is
    # failed (a run that crashes every worker must not loop forever).
    RUN_MAX_ATTEMPTS: int = 5
    # ── Schedules ──
    # Every worker checks for due schedules this often (a schedule fires at
    # most this late); off = this process never starts scheduled runs.
    BUILDER_SCHEDULER_ENABLED: bool = True
    SCHEDULE_POLL_SECONDS: float = 30.0
    # The most often a schedule may run.
    SCHEDULE_MIN_INTERVAL_MINUTES: int = 5
    # ── Versions ──
    # Saved versions kept per agent/workflow (the oldest go first).
    BUILDER_VERSIONS_KEEP: int = 100
    # Model calls: how many times to retry a failing model request.
    AGENT_MODEL_RETRY_DELAY_SECONDS: float = 2.0


@lru_cache
def get_builder_settings() -> BuilderSettings:
    return BuilderSettings()
