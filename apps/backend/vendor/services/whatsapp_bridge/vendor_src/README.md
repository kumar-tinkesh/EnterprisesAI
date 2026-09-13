# Vendored: whatsapp-mcp (patched)

Source: https://github.com/lharries/whatsapp-mcp
Commit: 7d6a06dcdce1f01dfb24f60e1030d5efba9f3b88
License: MIT (see `LICENSE`, copyright Luke Harries)

Vendored (not a git submodule) because this project needs to run **multiple
isolated instances** of the bridge concurrently — one per end-user — which
the upstream code doesn't support out of the box (see patches below). All
other behavior is unmodified upstream code.

## Patches applied

**`bridge/main.go`**
- The REST API port was hardcoded to `8080`. Two bridge instances (two
  users) on the same host would collide on that port. Now reads
  `WHATSAPP_BRIDGE_PORT` (falls back to `8080` if unset).
- Added `===EAI_QR_START===` / `===EAI_QR_END===` markers around the
  QR-code stdout block so our process manager can reliably extract exactly
  that block from the process's stdout instead of guessing at format.
- SQLite store paths were already relative to the process's *working
  directory* (`store/messages.db`, `store/whatsapp.db`) — no patch needed
  there; per-user isolation is achieved by launching each instance with a
  distinct `cwd`.
- Bumped `go.mau.fi/whatsmeow` from the upstream-pinned commit
  (2025-03-18) to latest. **Verified live**: the original pinned version is
  rejected outright by WhatsApp's servers today ("Client outdated (405)")
  before ever reaching the QR step — WhatsApp actively raises its minimum
  supported client version over time, so this isn't a one-time fix; expect
  to need to re-bump `whatsmeow` again in the future when it happens again.
  The version bump introduced 5 breaking API changes (added `context.Context`
  params to `client.Download`, `sqlstore.New`, `container.GetFirstDevice`,
  `client.Store.Contacts.GetContact`, `client.GetGroupInfo`) — patched to
  pass `context.Background()` at each call site.

**`server/whatsapp.py`**
- `WHATSAPP_API_BASE_URL` was a hardcoded `http://localhost:8080/api`
  constant — now reads the `WHATSAPP_API_BASE_URL` env var (same default),
  so each user's MCP server process talks to *their own* bridge's port.
- `MESSAGES_DB_PATH` was hardcoded relative to the script's own file
  location (`../whatsapp-bridge/store/messages.db`), which assumes one
  single, fixed bridge directory — now reads `WHATSAPP_MESSAGES_DB_PATH`
  (same default), pointed per-user at that user's own bridge's store.

See `apps/backend/vendor/services/whatsapp_bridge/manager.py` for how these
env vars get set per instance.
