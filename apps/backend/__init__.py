"""EnterpriseAI Backend application package.

Hosts two domain subsystems: ``vendor`` (MCP server registration/lifecycle,
owned by ``vendor_admin``) and ``user`` (read-only catalog/search/plan-tool
-call, any authenticated user). The FastAPI entrypoint lives in
:mod:`apps.backend.main`.
"""