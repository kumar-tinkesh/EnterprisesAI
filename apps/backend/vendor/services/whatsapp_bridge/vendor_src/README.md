# Vendored: whatsapp-mcp (patched)

Source: https://github.com/lharries/whatsapp-mcp
Commit: 7d6a06dcdce1f01dfb24f60e1030d5efba9f3b88
License: MIT (see `LICENSE`, copyright Luke Harries)

Both halves are taken from AI_Marketplace's vendored copies
(`services/whatsapp-bridge/` and `backend/vendor/whatsapp-mcp-server/`),
which already carry the patches for running **one bridge container per
user**; EnterpriseAI's own additions are listed separately below.

## How it runs here

- `bridge/` — the Go WhatsApp Web client. Built into its own image
  (`docker/Dockerfile.whatsapp_bridge`); one container per (server, user)
  bridge instance, started/stopped by the whatsapp-orchestrator service
  (`apps/whatsapp_orchestrator`), each with its own session volume
  (`eai-wa-store-<instance id>`, mounted at `/app/store`). The backend never
  sees a user's session files.
- `server/` — the Python MCP server. Runs as a stdio process of the backend
  or worker, pointed at that user's bridge container over the
  `enterpriseai_whatsapp` network (`WHATSAPP_API_BASE_URL`), and reads
  message history through the bridge's read endpoints rather than its
  SQLite file. See `vendor.services.whatsapp_bridge.manager` for how each
  instance's env is built.

## Patches from AI_Marketplace

**`bridge/main.go`**
- whatsmeow bumped to a recent version (WhatsApp rejects old clients with
  "Client outdated (405)"); call sites updated for its `context.Context`
  signatures. Expect to bump it again when pairing starts failing that way.
- `/api/status` + `pairingState`: the raw QR payload and
  waiting/connected/timeout state over HTTP, polled by the orchestrator.
- Read-only endpoints (`/api/messages`, `/api/chats`, `/api/contacts/...`)
  mirroring upstream's SQL with fixed queries on a `mode=ro` connection, so
  the MCP server needs no access to `messages.db`.
- Recipient JID resolved via `IsOnWhatsApp` before sending, bounded send
  timeouts, HTTP server timeouts.
- `WHATSAPP_BRIDGE_PORT` (default 8080).

**`server/whatsapp.py`, `server/main.py`**
- `WHATSAPP_API_BASE_URL` env-configurable; every read function calls the
  bridge's read endpoints instead of opening `messages.db`.

## EnterpriseAI additions

**`bridge/main.go`**
- `WHATSAPP_BRIDGE_TOKEN`: when set, every request must carry it as
  `X-Bridge-Token` (401 otherwise). The backend/worker — which run arbitrary
  vendor-registered MCP servers — share the bridge network, so network
  placement alone doesn't guard an API that can read and send as the user.
- `WHATSAPP_BRIDGE_HOST` (default `127.0.0.1`; the orchestrator sets
  `0.0.0.0` inside the bridge's own container).

**`server/`**
- Sends `WHATSAPP_BRIDGE_TOKEN` as `X-Bridge-Token` on every bridge request.
- `main.py` falls back to `mcp.server.mcpserver.MCPServer` when
  `mcp.server.fastmcp` is missing (mcp>=2 renamed it) — the server runs with
  the backend's own interpreter, which is on mcp 2.x.

## Known limits

- `send_file` / `send_audio_message` take a path the *bridge* must read, and
  `download_media` returns a path inside the bridge container — neither
  works across the container boundary (same as AI_Marketplace).
