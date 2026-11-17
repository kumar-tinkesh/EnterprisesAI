"""Durable runs of agents (and, in Phase 4, workflows).

    service   create / cancel runs, decide approvals (called by the API)
    queue     how a run id reaches a worker: in-process or Redis Streams
    lease     which worker holds a run (DB compare-and-set + heartbeat)
    worker    claim -> execute -> finish, plus the reaper that recovers lost runs
    executor  what "execute" means for each run kind
    events    live progress for WebSocket clients (in-process or Redis pub/sub)

The database is the source of truth. The queue only says "look at run X";
a run is executed only by the worker that wins its lease, so a duplicate
delivery, a Redis restart or a dead worker can delay a run but never run it
twice at the same time or lose it.
"""
