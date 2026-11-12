"""The platform admin's Overview and an account's detail."""
from __future__ import annotations

from datetime import timedelta

from builder.models import BuilderRun
from builder.runs.db import utcnow
from src.models import User
from vendor.services import mcp_auth

BASE = "/api/v1/vendor/resources"


async def test_overview_and_account(admin_client, tenant_client, db, tenant):
    db.add(User(id="u_1", tenant_id=tenant.id, email="a@x.io", full_name="Asha", role="tenant_admin"))
    for i, (st, cost, ago) in enumerate([("succeeded", 0.2, 0), ("failed", 0.1, 1), ("succeeded", 0.05, 20)]):
        db.add(BuilderRun(
            id=f"r{i}", tenant_id=tenant.id, owner_id="u_1", kind="agent", status=st, cost_usd=cost,
            input={}, definition={}, created_at=utcnow() - timedelta(days=ago),
        ))
    res = await admin_client.post(f"{BASE}/mcp", json={"name": "gmail", "description": "", "source_url": "https://mcp.example.com/g", "is_global": True})
    sid = res.json()["id"]
    await mcp_auth.store_server_credentials(db, server_id=sid, credentials={"K": "v"}, tenant_id=tenant.id, user_id="u_1")
    await db.commit()

    o = (await admin_client.get(f"{BASE}/platform/overview", params={"days": 7})).json()
    assert o["people_total"] >= 1 and o["new_people"]["current"] >= 1
    assert (o["runs"]["current"], o["failed_runs"]["current"]) == (2, 1)
    assert len(o["run_days"]) == 14 and sum(d["succeeded"] + d["failed"] for d in o["run_days"]) == 2
    assert len(o["signups_by_week"]) == 8
    assert o["top_apps"][0]["id"] == sid and o["top_apps"][0]["people"] == 1
    [acct] = o["top_accounts"]
    assert acct["id"] == tenant.id and acct["runs"] >= 2

    a = (await admin_client.get(f"{BASE}/platform/accounts/{tenant.id}")).json()
    assert [m["email"] for m in a["members"]] == ["a@x.io"] and a["apps"] == [{"id": sid, "name": "gmail", "people": 1}]
    assert a["failed_month"] >= 1 and a["runs_month"] >= 2

    assert (await tenant_client.get(f"{BASE}/platform/overview")).status_code == 403
    assert (await admin_client.get(f"{BASE}/platform/accounts/nope")).status_code == 404
