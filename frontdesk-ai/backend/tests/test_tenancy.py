import base64
import json

from tests.conftest import PASSWORD, h, register


def test_register_creates_business_with_trial(client):
    out = register(client)
    orgs = client.get("/api/v1/orgs", headers=h(out)).json()
    assert len(orgs) == 1 and orgs[0]["role"] == "owner" and orgs[0]["subscription_status"] == "trialing"
    assistant = client.get("/api/v1/assistant", headers=h(out)).json()
    assert assistant["widget_key"].startswith("wk_")
    assert "Alice Salon" in assistant["greeting"]


def test_register_requires_business_or_invite(client):
    r = client.post("/api/v1/auth/register", json={"email": "x@example.com", "password": PASSWORD})
    assert r.status_code == 422


def test_login_refresh_logout(client):
    out = register(client)
    old = client.cookies.get("fd_rt")
    assert client.post("/api/v1/auth/refresh").status_code == 200
    client.cookies.clear()
    client.cookies.set("fd_rt", old)
    assert client.post("/api/v1/auth/refresh").status_code == 401  # reuse detected -> family revoked
    assert client.get("/api/v1/org", headers=h(out)).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": PASSWORD}).status_code == 200


def test_jwt_alg_none_rejected(client):
    out = register(client)
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    forged = f"{header}.{out['access_token'].split('.')[1]}."
    assert client.get("/api/v1/org", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_cross_tenant_isolation(client):
    alice = register(client, "alice@example.com", "Alice Salon")
    bob = register(client, "bob@example.com", "Bob Gym")
    alice_org = client.get("/api/v1/org", headers=h(alice)).json()["id"]
    contact = client.post("/api/v1/contacts", json={"name": "Carol", "email": "carol@example.com"},
                          headers=h(alice)).json()
    svc = client.get("/api/v1/services", headers=h(alice)).json()[0]
    # Bob cannot select Alice's org
    assert client.get("/api/v1/contacts", headers=h(bob, alice_org)).status_code == 404
    # Bob's own org doesn't see Alice's data, and can't touch it by id
    assert client.get("/api/v1/contacts", headers=h(bob)).json() == []
    assert client.put(f"/api/v1/contacts/{contact['id']}", json={"name": "pwned"}, headers=h(bob)).status_code == 404
    assert client.put(f"/api/v1/services/{svc['id']}", json={"name": "pwned"}, headers=h(bob)).status_code == 404
    assert client.post("/api/v1/appointments", json={"service_id": svc["id"], "start": "2030-01-01T10:00:00+00:00",
                                                     "name": "x"}, headers=h(bob)).status_code == 409


def test_invitation_and_roles(client):
    owner = register(client)
    r = client.post("/api/v1/org/invitations", json={"email": "sam@example.com", "role": "staff"}, headers=h(owner))
    assert r.status_code == 201
    token = r.json()["invite_url"].split("#token=")[1]
    # wrong email can't use the invite
    other = register(client, "eve@example.com", "Eve Co")
    assert client.post("/api/v1/invitations/accept", json={"token": token}, headers=h(other)).status_code == 403
    staff = register(client, "sam@example.com", invite_token=token)
    orgs = client.get("/api/v1/orgs", headers=h(staff)).json()
    assert len(orgs) == 1 and orgs[0]["role"] == "staff"
    # staff can read the inbox but not reconfigure the assistant or invite
    assert client.get("/api/v1/conversations", headers=h(staff)).status_code == 200
    cfg = client.get("/api/v1/assistant", headers=h(staff)).json()
    cfg.pop("widget_key"), cfg.pop("updated_at")
    assert client.put("/api/v1/assistant", json=cfg, headers=h(staff)).status_code == 403
    assert client.post("/api/v1/org/invitations", json={"email": "z@example.com"}, headers=h(staff)).status_code == 403
    # invite can't be reused
    assert client.post("/api/v1/invitations/accept", json={"token": token}, headers=h(other)).status_code == 400


def test_last_owner_cannot_leave(client):
    owner = register(client)
    me = client.get("/api/v1/org/members", headers=h(owner)).json()[0]
    assert client.delete(f"/api/v1/org/members/{me['id']}", headers=h(owner)).status_code == 400
    assert client.patch(f"/api/v1/org/members/{me['id']}", json={"role": "staff"}, headers=h(owner)).status_code == 400


def test_member_limit_enforced(client):
    owner = register(client)
    for i in range(4):  # growth trial: 5 members incl. owner
        assert client.post("/api/v1/org/invitations", json={"email": f"p{i}@example.com"}, headers=h(owner)).status_code == 201
    assert client.post("/api/v1/org/invitations", json={"email": "p9@example.com"}, headers=h(owner)).status_code == 402


def test_platform_admin_hidden_from_others(client):
    normal = register(client)
    assert client.get("/api/v1/admin/stats", headers=h(normal)).status_code == 404
    founder = register(client, "founder@example.com", "Platform HQ")
    stats = client.get("/api/v1/admin/stats", headers=h(founder)).json()
    assert stats["businesses"] == 2


def test_delete_account_removes_solo_org(client):
    out = register(client)
    r = client.request("DELETE", "/api/v1/account", json={"password": PASSWORD, "confirm": "DELETE"}, headers=h(out))
    assert r.status_code == 204
    assert client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": PASSWORD}).status_code == 401
