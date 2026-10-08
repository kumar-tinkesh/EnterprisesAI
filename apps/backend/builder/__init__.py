"""Builder domain: what agents and workflows need to actually *do* things.

Phase 1 is the MCP tool runtime (``builder.services.tool_runtime``): calling a
tool on an MCP server as a specific end user — with that user's own
credentials, an isolated per-user process home, pooled long-lived sessions,
timeouts, argument validation and a read/edit/delete risk classification.

Later phases add agents, workflows and their runs on top of it.

Unlike the read-only ``user`` domain, builder may use vendor's connection
services (``vendor.services.mcp_service`` / ``mcp_client``) — it needs them
to run tools — but never vendor's admin API, registration or detection code
(see the import-linter contracts in pyproject.toml).
"""
