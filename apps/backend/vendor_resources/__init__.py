"""Vendor Resources subsystem — capability catalog layer (MCP).

Phase 1 scope: MCP server CRUD, tenant resource grants, and an
access-filtered catalog.

All imports are absolute from the project root (no relative imports).

NOTE: the router is imported *lazily* (via module ``__getattr__``). Importing
this package must remain cheap and free of side effects, because Alembic's
``env.py`` imports ``vendor_resources.models`` to register the vendor tables
on the shared ``Base.metadata`` — an eager router import would pull in FastAPI,
the MCP SDK and settings machinery in every alembic run.
"""

__all__ = ["router"]


def __getattr__(name: str):
    if name == "router":
        from vendor_resources.router import router

        return router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")