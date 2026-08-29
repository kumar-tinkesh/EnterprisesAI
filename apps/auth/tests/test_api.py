"""End-to-end API tests for unified signup/login, /me, refresh, logout, and the
role-scoped dashboards (vendor/tenant/user)."""
from __future__ import annotations

from sqlalchemy import select

from src.models import RefreshToken, Tenant, VendorUser


async def _signup(client, **overrides):
    payload = {
        "email": "dev@example.com",
        "password": "str0ng!pass",
        "full_name": "Dev User",
        "role": "solo_user",
        "tenant_name": "Personal",
    }
    payload.update(overrides)
    return await client.post("/api/v1/auth/signup", json=payload)


async def _login(client, email="dev@example.com", password="str0ng!pass", **kw):
    body = {"email": email, "password": password}
    body.update(kw)
    return await client.post("/api/v1/auth/login", json=body)


async def _token(resp):
    return resp.json()["access_token"]


async def _create_vendor_admin_access(client):
    await _signup(client, email="vendor@platform.io", role="vendor_admin")
    return await _token(await _login(client, email="vendor@platform.io"))


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["service"] == "auth"


async def test_jwks_public_endpoint(client):
    resp = await client.get("/.well-known/jwks.json")
    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert keys
    assert keys[0]["kty"] == "RSA"
    assert keys[0]["use"] == "sig"


async def test_signup_solo_user_returns_tokens(client, db):
    resp = await _signup(client)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["role"] == "solo_user"
    assert body["user"]["email"] == "dev@example.com"

    tokens = list((await db.execute(select(RefreshToken))).scalars())
    assert len(tokens) == 1
    assert tokens[0].token_hash != body["refresh_token"]


async def test_signup_duplicate_conflict(client):
    assert (await _signup(client)).status_code == 201
    assert (await _signup(client)).status_code == 409


async def test_signup_tenant_user_disabled(client):
    """Tenant user self-signup is disabled and returns 400 Bad Request."""
    resp = await _signup(client, email="employee@corp.com", role="tenant_user")
    assert resp.status_code == 400
    assert "disabled" in resp.json()["detail"].lower()


async def test_signup_tenant_admin_disabled(client):
    """Tenant admin self-signup is disabled and returns 400 Bad Request."""
    resp = await _signup(client, email="admin@corp.com", role="tenant_admin")
    assert resp.status_code == 400
    assert "disabled" in resp.json()["detail"].lower()


async def test_tenant_member_crud(client):
    """Vendor admin provisions tenant, then Tenant admin can manage members."""
    vendor_access = await _create_vendor_admin_access(client)
    create_tenant_res = await client.post(
        "/api/v1/vendor/tenants",
        headers={"Authorization": f"Bearer {vendor_access}"},
        json={
            "name": "Acme Corp",
            "admin_email": "admin@corp.com",
            "admin_full_name": "Acme Admin",
            "admin_password": "str0ng!pass",
        },
    )
    assert create_tenant_res.status_code == 201

    admin_access = await _token(await _login(client, email="admin@corp.com"))
    headers = {"Authorization": f"Bearer {admin_access}"}

    # 1. Stats (initially 0 regular tenant_user members)
    stats_res = await client.get("/api/v1/tenant/stats", headers=headers)
    assert stats_res.status_code == 200, stats_res.text
    assert stats_res.json()["workspace_count"] == 1
    assert stats_res.json()["member_count"] == 0

    # 2. List members (initially empty)
    members_res = await client.get("/api/v1/tenant/members", headers=headers)
    assert members_res.status_code == 200
    members = members_res.json()
    assert len(members) == 0

    # 3. Create tenant user (defaults to tenant_user)
    create_res = await client.post(
        "/api/v1/tenant/members",
        headers=headers,
        json={"email": "new.member@corp.com", "password": "Password123", "full_name": "New Employee"},
    )
    assert create_res.status_code == 201, create_res.text
    new_user = create_res.json()
    assert new_user["email"] == "new.member@corp.com"
    assert new_user["role"] == "tenant_user"

    # Verify updated stats (1 regular tenant_user member)
    stats_res2 = await client.get("/api/v1/tenant/stats", headers=headers)
    assert stats_res2.json()["member_count"] == 1

    # 4. Update member (toggle active)
    patch_res = await client.patch(
        f"/api/v1/tenant/members/{new_user['id']}",
        headers=headers,
        json={"is_active": False, "full_name": "New Employee Updated"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["is_active"] is False
    assert patch_res.json()["full_name"] == "New Employee Updated"

    # 5. Delete member
    del_res = await client.delete(f"/api/v1/tenant/members/{new_user['id']}", headers=headers)
    assert del_res.status_code == 204

    # Verify member count decreased back to 0
    stats_res3 = await client.get("/api/v1/tenant/stats", headers=headers)
    assert stats_res3.json()["member_count"] == 0


async def test_signup_vendor_admin(client, db):
    resp = await _signup(client, email="priya@enterpriseai.io", role="vendor_admin")
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["role"] == "vendor_admin"
    vendors = list((await db.execute(select(VendorUser))).scalars())
    assert len(vendors) == 1


async def test_signup_invalid_role(client):
    resp = await _signup(client, role="superuser")
    assert resp.status_code == 422


async def test_login_and_me(client):
    await _signup(client)
    login = await _login(client)
    assert login.status_code == 200, login.text
    access = await _token(login)

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "dev@example.com"
    assert me.json()["role"] == "solo_user"


async def test_login_wrong_password(client):
    await _signup(client)
    login = await _login(client, password="bad-password")
    assert login.status_code == 401


async def test_me_without_token(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_refresh_rotation(client):
    await _signup(client)
    login = await _login(client)
    refresh = login.json()["refresh_token"]

    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh}
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["access_token"]
    assert refreshed.json()["refresh_token"] != refresh

    again = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert again.status_code == 401


async def test_logout_revokes(client):
    await _signup(client)
    login = await _login(client)
    refresh = login.json()["refresh_token"]
    out = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert out.status_code == 200
    re_use = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert re_use.status_code == 401


# --- Role-scoped dashboards -------------------------------------------------

async def _signup_and_login(client, role):
    email = f"{role}@example.com"
    if role == "vendor_admin" or role == "solo_user":
        await _signup(client, email=email, role=role)
    elif role == "tenant_admin":
        v_access = await _create_vendor_admin_access(client)
        await client.post(
            "/api/v1/vendor/tenants",
            headers={"Authorization": f"Bearer {v_access}"},
            json={
                "name": "Test Org",
                "admin_email": email,
                "admin_full_name": "Org Admin",
                "admin_password": "str0ng!pass",
            },
        )
    elif role == "tenant_user":
        v_access = await _create_vendor_admin_access(client)
        admin_email = f"admin_{email}"
        await client.post(
            "/api/v1/vendor/tenants",
            headers={"Authorization": f"Bearer {v_access}"},
            json={
                "name": "User Org",
                "admin_email": admin_email,
                "admin_full_name": "Org Admin",
                "admin_password": "str0ng!pass",
            },
        )
        t_access = await _token(await _login(client, email=admin_email))
        await client.post(
            "/api/v1/tenant/members",
            headers={"Authorization": f"Bearer {t_access}"},
            json={"email": email, "password": "str0ng!pass", "full_name": "Tenant Employee"},
        )
    return await _token(await _login(client, email=email))


async def test_dashboard_vendor_accessible_for_vendor(client):
    access = await _signup_and_login(client, "vendor_admin")
    resp = await client.get(
        "/api/v1/dashboard/vendor", headers={"Authorization": f"Bearer {access}"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "vendor_admin"
    assert resp.json()["dashboard"] == "vendor"


async def test_dashboard_tenant_accessible_for_tenant_admin(client):
    access = await _signup_and_login(client, "tenant_admin")
    resp = await client.get(
        "/api/v1/dashboard/tenant", headers={"Authorization": f"Bearer {access}"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "tenant_admin"


async def test_dashboard_user_accessible_for_tenant_user(client):
    access = await _signup_and_login(client, "tenant_user")
    resp = await client.get(
        "/api/v1/dashboard/user", headers={"Authorization": f"Bearer {access}"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "tenant_user"


async def test_dashboard_wrong_role_forbidden(client):
    # A tenant_user must not access the tenant_admin dashboard.
    access = await _signup_and_login(client, "tenant_user")
    resp = await client.get(
        "/api/v1/dashboard/tenant", headers={"Authorization": f"Bearer {access}"}
    )
    assert resp.status_code == 403
    resp2 = await client.get(
        "/api/v1/dashboard/vendor", headers={"Authorization": f"Bearer {access}"}
    )
    assert resp2.status_code == 403


# --- Solo user tests --------------------------------------------------------

async def test_signup_solo_user(client, db):
    """Solo user signup auto-creates a personal tenant + workspace."""
    resp = await _signup(client, email="solo@dev.io", role="solo_user", full_name="Solo Dev")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["role"] == "solo_user"
    assert body["user"]["tenant_id"] is not None
    assert body["access_token"]
    assert body["refresh_token"]

    # Verify the auto-created tenant is marked as personal
    tenant = (await db.execute(select(Tenant).where(Tenant.is_personal.is_(True)))).scalars().first()
    assert tenant is not None
    assert "Solo Dev" in tenant.name


async def test_solo_user_login_and_me(client):
    """Solo user can log in and access /me."""
    await _signup(client, email="solo2@dev.io", role="solo_user", full_name="Solo Two")
    login = await _login(client, email="solo2@dev.io")
    assert login.status_code == 200, login.text
    access = await _token(login)

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    assert me.json()["role"] == "solo_user"
    assert me.json()["email"] == "solo2@dev.io"


async def test_solo_user_accesses_workspace_dashboard(client):
    """Solo user can access the user workspace dashboard."""
    access = await _signup_and_login(client, "solo_user")
    resp = await client.get(
        "/api/v1/dashboard/user", headers={"Authorization": f"Bearer {access}"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["dashboard"] == "user"


async def test_solo_user_cannot_access_vendor_dashboard(client):
    """Solo user must not access vendor or tenant dashboards."""
    access = await _signup_and_login(client, "solo_user")
    resp = await client.get(
        "/api/v1/dashboard/vendor", headers={"Authorization": f"Bearer {access}"}
    )
    assert resp.status_code == 403
    resp2 = await client.get(
        "/api/v1/dashboard/tenant", headers={"Authorization": f"Bearer {access}"}
    )
    assert resp2.status_code == 403


# --- Vendor admin stats and tenant management tests -------------------------

async def test_vendor_stats_and_tenant_crud(client):
    """Vendor admin can view platform stats (including individual users) and manage tenants."""
    access = await _signup_and_login(client, "vendor_admin")
    headers = {"Authorization": f"Bearer {access}"}

    # Also create a solo user so individual_users count > 0
    await _signup(client, email="solo_test@dev.io", role="solo_user", full_name="Solo Person")

    # 1. Vendor stats
    stats_res = await client.get("/api/v1/vendor/stats", headers=headers)
    assert stats_res.status_code == 200, stats_res.text
    body = stats_res.json()
    assert "total_tenants" in body
    assert body["individual_users"] >= 1
    assert body["total_users"] >= 2

    # 2. List tenants
    tenants_res = await client.get("/api/v1/vendor/tenants", headers=headers)
    assert tenants_res.status_code == 200

    # 3. Create tenant
    create_res = await client.post(
        "/api/v1/vendor/tenants",
        headers=headers,
        json={
            "name": "Stark Industries",
            "admin_email": "tony@stark.com",
            "admin_full_name": "Tony Stark",
            "admin_password": "Password123!",
        },
    )
    assert create_res.status_code == 201, create_res.text
    tenant = create_res.json()
    assert tenant["name"] == "Stark Industries"
    assert tenant["admin_email"] == "tony@stark.com"

    # 4. Suspend tenant
    patch_res = await client.patch(
        f"/api/v1/vendor/tenants/{tenant['id']}",
        headers=headers,
        json={"status": "suspended"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "suspended"

    # 5. Delete tenant
    del_res = await client.delete(f"/api/v1/vendor/tenants/{tenant['id']}", headers=headers)
    assert del_res.status_code == 204


async def test_audit_logs_and_tenant_sso_config(client):
    """Test audit log creation upon login/signup and per-tenant SSO config management."""
    # 1. Signup solo user (generates audit event)
    signup_res = await _signup(client, email="audit_user@example.com", role="solo_user")
    assert signup_res.status_code == 201
    access = await _token(await _login(client, email="audit_user@example.com"))
    headers = {"Authorization": f"Bearer {access}"}

    # 2. Query audit logs
    audit_res = await client.get("/api/v1/auth/audit-logs", headers=headers)
    assert audit_res.status_code == 200, audit_res.text
    logs = audit_res.json()
    assert len(logs) >= 2  # signup + login events
    actions = [l["action"] for l in logs]
    assert "signup" in actions
    assert "login" in actions

    # 3. Create SSO config for tenant
    sso_post = await client.post(
        "/api/v1/sso/config",
        headers=headers,
        json={
            "provider": "okta",
            "client_id": "okta-client-123",
            "client_secret": "okta-secret-456",
            "discovery_url": "https://okta.example.com/.well-known/openid-configuration",
            "enabled": True,
        },
    )
    assert sso_post.status_code == 200, sso_post.text
    assert sso_post.json()["provider"] == "okta"
    assert sso_post.json()["client_id"] == "okta-client-123"

    # 4. Fetch SSO config for tenant
    sso_get = await client.get("/api/v1/sso/config", headers=headers)
    assert sso_get.status_code == 200
    assert sso_get.json()["provider"] == "okta"

