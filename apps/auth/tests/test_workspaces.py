"""Workspaces: a solo account has exactly one; a tenant can have many.

Creating, listing, members, switching (a new token for the chosen workspace),
refresh keeping the chosen workspace, and every refusal along the way."""
from __future__ import annotations

from src.core.security import decode_token

from apps.auth.tests.test_api import _create_vendor_admin_access, _login, _signup, _token

PW = "str0ng!pass"


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _wid(token: str) -> str | None:
    return decode_token(token, expected_type="access").get("wid")


async def _tenant(client) -> dict:
    """Acme with its admin, plus one member Bob (added to the first workspace)."""
    vendor = await _create_vendor_admin_access(client)
    r = await client.post(
        "/api/v1/vendor/tenants", headers=_h(vendor),
        json={"name": "Acme", "admin_email": "admin@acme.io", "admin_full_name": "Ada Admin", "admin_password": PW},
    )
    assert r.status_code == 201, r.text
    admin_login = (await _login(client, email="admin@acme.io")).json()
    admin = admin_login["access_token"]
    r = await client.post(
        "/api/v1/tenant/members", headers=_h(admin),
        json={"email": "bob@acme.io", "password": PW, "full_name": "Bob Member"},
    )
    assert r.status_code == 201, r.text
    bob_id = r.json()["id"]
    bob_login = (await _login(client, email="bob@acme.io")).json()
    return {
        "admin": admin, "admin_refresh": admin_login["refresh_token"], "admin_id": admin_login["user"]["id"],
        "first_ws": admin_login["user"]["workspace_id"], "bob": bob_login["access_token"], "bob_id": bob_id,
    }


async def test_solo_account_has_one_workspace_and_no_switching(client):
    signup = (await _signup(client)).json()
    token = signup["access_token"]
    assert signup["user"]["workspace_id"] and _wid(token) == signup["user"]["workspace_id"]

    r = await client.get("/api/v1/workspaces", headers=_h(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["workspaces"]) == 1 and body["workspaces"][0]["is_current"]
    assert body["can_create"] is False and body["can_switch"] is False

    r = await client.post("/api/v1/workspaces", headers=_h(token), json={"name": "Second"})
    assert r.status_code == 403 and "personal account" in r.json()["detail"]
    r = await client.post(f"/api/v1/workspaces/{body['current_id']}/switch", headers=_h(token))
    assert r.status_code == 403

    me = (await client.get("/api/v1/auth/me", headers=_h(token))).json()
    assert me["workspace_id"] == body["current_id"] and me["workspace_name"]


async def test_tenant_admin_creates_switches_and_refresh_keeps_it(client):
    t = await _tenant(client)
    admin = t["admin"]

    listed = (await client.get("/api/v1/workspaces", headers=_h(admin))).json()
    assert listed["can_create"] is True and listed["can_switch"] is False
    assert [w["id"] for w in listed["workspaces"]] == [t["first_ws"]]

    r = await client.post("/api/v1/workspaces", headers=_h(admin), json={"name": "Sales", "description": "Deals"})
    assert r.status_code == 201, r.text
    sales = r.json()
    assert sales["name"] == "Sales" and sales["description"] == "Deals" and sales["my_role"] == "admin"
    assert sales["member_count"] == 1 and sales["is_current"] is False

    r = await client.post("/api/v1/workspaces", headers=_h(admin), json={"name": "sales"})
    assert r.status_code == 409

    listed = (await client.get("/api/v1/workspaces", headers=_h(admin))).json()
    assert listed["can_switch"] is True and len(listed["workspaces"]) == 2

    r = await client.post(f"/api/v1/workspaces/{sales['id']}/switch", headers=_h(admin))
    assert r.status_code == 200, r.text
    switched = r.json()
    assert _wid(switched["access_token"]) == sales["id"] and switched["user"]["workspace_id"] == sales["id"]
    me = (await client.get("/api/v1/auth/me", headers=_h(switched["access_token"]))).json()
    assert me["workspace_id"] == sales["id"] and me["workspace_name"] == "Sales"

    # A refreshed token stays in the workspace switched to.
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": switched["refresh_token"]})
    assert r.status_code == 200 and _wid(r.json()["access_token"]) == sales["id"]

    # Logging in again can ask for it too.
    r = await _login(client, email="admin@acme.io", workspace_id=sales["id"])
    assert r.json()["user"]["workspace_id"] == sales["id"]


async def test_member_sees_only_their_workspaces_and_cannot_enter_others(client):
    t = await _tenant(client)
    sales = (await client.post("/api/v1/workspaces", headers=_h(t["admin"]), json={"name": "Sales"})).json()

    bob = (await client.get("/api/v1/workspaces", headers=_h(t["bob"]))).json()
    assert [w["id"] for w in bob["workspaces"]] == [t["first_ws"]]
    assert bob["can_create"] is False and bob["can_switch"] is False

    # Not a member: can't switch in, can't see members, can't create.
    assert (await client.post(f"/api/v1/workspaces/{sales['id']}/switch", headers=_h(t["bob"]))).status_code == 404
    assert (await client.get(f"/api/v1/workspaces/{sales['id']}/members", headers=_h(t["bob"]))).status_code == 404
    assert (await client.post("/api/v1/workspaces", headers=_h(t["bob"]), json={"name": "Mine"})).status_code == 403

    # A forged token pointing at it falls back to his own workspace.
    r = await _login(client, email="bob@acme.io", workspace_id=sales["id"])
    assert r.json()["user"]["workspace_id"] == t["first_ws"]

    # Added by the admin: now he sees it and can switch.
    r = await client.post(
        f"/api/v1/workspaces/{sales['id']}/members", headers=_h(t["admin"]), json={"user_id": t["bob_id"]}
    )
    assert r.status_code == 201 and {m["email"] for m in r.json()} == {"admin@acme.io", "bob@acme.io"}
    bob = (await client.get("/api/v1/workspaces", headers=_h(t["bob"]))).json()
    assert len(bob["workspaces"]) == 2 and bob["can_switch"] is True
    switched = await client.post(f"/api/v1/workspaces/{sales['id']}/switch", headers=_h(t["bob"]))
    assert switched.status_code == 200

    # A member can't rename it; removed again, his switched token falls back.
    assert (await client.patch(f"/api/v1/workspaces/{sales['id']}", headers=_h(t["bob"]), json={"name": "X"})).status_code == 403
    r = await client.delete(f"/api/v1/workspaces/{sales['id']}/members/{t['bob_id']}", headers=_h(t["admin"]))
    assert r.status_code == 204
    me = (await client.get("/api/v1/auth/me", headers=_h(switched.json()["access_token"]))).json()
    assert me["workspace_id"] == t["first_ws"]


async def test_rename_archive_and_the_last_admin(client):
    t = await _tenant(client)
    admin = t["admin"]
    sales = (await client.post("/api/v1/workspaces", headers=_h(admin), json={"name": "Sales"})).json()

    r = await client.patch(f"/api/v1/workspaces/{sales['id']}", headers=_h(admin), json={"name": "Revenue"})
    assert r.status_code == 200 and r.json()["name"] == "Revenue"

    # The only admin of Sales can't be demoted or removed.
    r = await client.patch(
        f"/api/v1/workspaces/{sales['id']}/members/{t['admin_id']}", headers=_h(admin), json={"role": "member"}
    )
    assert r.status_code == 400
    r = await client.delete(f"/api/v1/workspaces/{sales['id']}/members/{t['admin_id']}", headers=_h(admin))
    assert r.status_code == 400

    # Archive: gone from the list (unless asked), can't be entered.
    r = await client.patch(f"/api/v1/workspaces/{sales['id']}", headers=_h(admin), json={"status": "archived"})
    assert r.status_code == 200 and r.json()["status"] == "archived"
    assert [w["id"] for w in (await client.get("/api/v1/workspaces", headers=_h(admin))).json()["workspaces"]] == [t["first_ws"]]
    every = (await client.get("/api/v1/workspaces?include_archived=true", headers=_h(admin))).json()["workspaces"]
    assert len(every) == 2
    assert (await client.post(f"/api/v1/workspaces/{sales['id']}/switch", headers=_h(admin))).status_code == 404

    # The last active one can't be archived.
    r = await client.patch(f"/api/v1/workspaces/{t['first_ws']}", headers=_h(admin), json={"status": "archived"})
    assert r.status_code == 400


async def test_other_tenants_workspaces_are_invisible(client):
    t = await _tenant(client)
    solo = (await _signup(client, email="solo@x.io")).json()["access_token"]
    sales = (await client.post("/api/v1/workspaces", headers=_h(t["admin"]), json={"name": "Sales"})).json()
    assert (await client.post(f"/api/v1/workspaces/{sales['id']}/switch", headers=_h(solo))).status_code == 403
    assert (await client.get(f"/api/v1/workspaces/{sales['id']}/members", headers=_h(solo))).status_code == 403
    r = await client.post(
        f"/api/v1/workspaces/{sales['id']}/members", headers=_h(t["admin"]),
        json={"user_id": decode_token(solo, expected_type="access")["sub"]},
    )
    assert r.status_code == 404  # not in this tenant
    vendor = await _token(await _login(client, email="vendor@platform.io"))
    assert (await client.get("/api/v1/workspaces", headers=_h(vendor))).status_code == 403
