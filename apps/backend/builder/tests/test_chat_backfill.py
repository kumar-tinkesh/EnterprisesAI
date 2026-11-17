"""Migration a2b3c4d5e6f7: earlier runs started from the editor get a chat each, so they show in Chat history."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import select

from builder.models import BuilderRun


def _migration():
    path = Path(__file__).resolve().parents[3] / "auth" / "alembic" / "versions" / "a2b3c4d5e6f7_runs_into_chats.py"
    spec = importlib.util.spec_from_file_location("m_a2b3", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_editor_runs_become_chats_and_scheduled_ones_dont(db, tenant_client, tenant_user):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    common = dict(tenant_id=tenant_user.tenant_id, owner_id=tenant_user.id, kind="workflow", workflow_id="wf-1", status="succeeded")
    editor = BuilderRun(**common, input={"text": "find IT leads in Gurgaon"}, purpose="run")
    fields_only = BuilderRun(**common, input={"text": "", "variables": {"offer": "cloud migration"}}, purpose="run")
    scheduled = BuilderRun(**common, input={"text": "daily"}, purpose="run", schedule_id="sch-1")
    test_run = BuilderRun(**common, input={"text": "case"}, purpose="test")
    db.add_all([editor, fields_only, scheduled, test_run])
    await db.commit()

    def run(sync_conn):
        with Operations.context(MigrationContext.configure(sync_conn)):
            _migration().upgrade()

    await (await db.connection()).run_sync(run)
    await db.commit()

    rows = {r.id: r for r in (await db.execute(select(BuilderRun))).scalars()}
    for r in rows.values():
        await db.refresh(r)
    assert rows[editor.id].conversation_id and rows[fields_only.id].conversation_id
    assert rows[editor.id].conversation_id != rows[fields_only.id].conversation_id
    assert rows[scheduled.id].conversation_id is None and rows[test_run.id].conversation_id is None

    chats = (await tenant_client.get("/api/v1/builder/conversations", params={"workflow_id": "wf-1"})).json()
    titles = sorted(c["title"] for c in chats)
    assert titles == ["cloud migration", "find IT leads in Gurgaon"]
    runs = (await tenant_client.get(f"/api/v1/builder/conversations/{rows[editor.id].conversation_id}/runs")).json()
    assert [r["id"] for r in runs] == [editor.id]
