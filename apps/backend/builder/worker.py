"""Run the builder worker as its own process (BUILDER_QUEUE_BACKEND=redis).

    cd apps/backend && python -m builder.worker

Stops cleanly on SIGINT/SIGTERM: in-flight runs are left checkpointed and
their leases lapse, so another worker resumes them.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (ROOT, ROOT / "apps" / "auth", ROOT / "apps" / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


async def main() -> None:
    import vendor.models  # noqa: F401  (register every table on the metadata)
    import knowledge.models  # noqa: F401
    from builder.config import get_builder_settings
    from builder.runs.worker import Worker
    from builder.services.tool_runtime import shutdown_pool

    settings = get_builder_settings()
    if settings.BUILDER_QUEUE_BACKEND != "redis":
        logging.getLogger("builder.worker").warning(
            "BUILDER_QUEUE_BACKEND is %r: the API process runs its own worker; a separate one only helps with redis.",
            settings.BUILDER_QUEUE_BACKEND,
        )
    worker = Worker()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await worker.start()
    await worker.reap()  # pick up anything left behind by a previous worker right away
    await stop.wait()
    await worker.stop()
    await shutdown_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
