import hashlib
import hmac
import json
import time
from datetime import date, datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import Appointment, Contact, MessageLog, Organization
from app.services.notify import run_birthdays, run_reminders, unsubscribe_url
from tests.conftest import h, open_all_day, register


def signed(payload: dict, secret: str = "whsec_test_secret") -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    t = int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return body, f"t={t},v1={sig}"


def test_webhook_signature_and_subscription_update(client):
    owner = register(client)
    org_id = client.get("/api/v1/org", headers=h(owner)).json()["id"]
    event = {"id": "evt_1", "type": "customer.subscription.updated", "data": {"object": {
        "id": "sub_1", "customer": "cus_1", "status": "active", "metadata": {"org_id": org_id},
        "current_period_end": int(time.time()) + 86400 * 30,
        "items": {"data": [{"price": {"id": "price_pro"}}]}}}}
    body, sig = signed(event)
    bad = client.post("/api/v1/billing/webhook", content=body, headers={"Stripe-Signature": sig.replace("v1=", "v1=00")})
    assert bad.status_code == 400
    forged_body, forged_sig = signed(event, secret="attacker")
    forged = client.post("/api/v1/billing/webhook", content=forged_body, headers={"Stripe-Signature": forged_sig})
    assert forged.status_code == 400
    ok = client.post("/api/v1/billing/webhook", content=body, headers={"Stripe-Signature": sig})
    assert ok.status_code == 200
    org = client.get("/api/v1/org", headers=h(owner)).json()
    assert org["plan"] == "pro" and org["subscription_status"] == "active"
    dup = client.post("/api/v1/billing/webhook", content=body, headers={"Stripe-Signature": sig})
    assert dup.json().get("duplicate") is True


def test_billing_overview(client):
    owner = register(client)
    b = client.get("/api/v1/billing", headers=h(owner)).json()
    assert b["status"] == "trialing" and len(b["plans"]) == 3 and b["usage"]["conversation_limit"] == 1500


def test_reminders_sent_once(client):
    owner = register(client)
    hdr = h(owner)
    open_all_day(client, hdr)
    svc = client.get("/api/v1/services", headers=hdr).json()[0]
    start = (datetime.now(timezone.utc) + timedelta(hours=5)).replace(second=0, microsecond=0)
    r = client.post("/api/v1/appointments", headers=hdr, json={
        "service_id": svc["id"], "start": start.isoformat(), "name": "Finn", "email": "finn@example.com",
        "skip_availability_check": True})
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        assert run_reminders(db) == 1
        db.commit()
        assert run_reminders(db) == 0
        assert db.query(Appointment).one().reminder_sent_at is not None


def test_birthdays_require_consent_and_send_once(client):
    owner = register(client, tz="UTC")
    hdr = h(owner)
    cfg = open_all_day(client, hdr, birthday_enabled=True)
    assert cfg["birthday_enabled"]
    today = date.today()
    client.post("/api/v1/contacts", headers=hdr, json={"name": "Gina", "email": "gina@example.com",
                                                       "birthday": today.replace(year=1991).isoformat(),
                                                       "marketing_consent": True})
    client.post("/api/v1/contacts", headers=hdr, json={"name": "Hal", "email": "hal@example.com",
                                                       "birthday": today.replace(year=1985).isoformat(),
                                                       "marketing_consent": False})
    noon = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=12)
    with SessionLocal() as db:
        assert run_birthdays(db, now=noon) == 1
        db.commit()
        assert run_birthdays(db, now=noon) == 0
        assert db.query(MessageLog).filter(MessageLog.kind == "birthday").one().to == "gina@example.com"
        gina = db.query(Contact).filter(Contact.email == "gina@example.com").one()
        url = unsubscribe_url(gina.id)
    path = url.split("localhost:5173")[1]
    assert client.get(path).status_code == 200
    assert client.get(path.replace("&s=", "&s=0")).text.count("invalid") == 1
    contact = [c for c in client.get("/api/v1/contacts", headers=hdr).json() if c["name"] == "Gina"][0]
    assert contact["marketing_consent"] is False and contact["unsubscribed_at"]


def test_starter_plan_has_no_birthday_wishes(client):
    owner = register(client, tz="UTC")
    hdr = h(owner)
    open_all_day(client, hdr, birthday_enabled=True)
    with SessionLocal() as db:
        db.query(Organization).update({"plan": "starter"})
        db.commit()
    client.post("/api/v1/contacts", headers=hdr, json={"name": "Ivy", "email": "ivy@example.com",
                                                       "birthday": date.today().replace(year=1990).isoformat(),
                                                       "marketing_consent": True})
    with SessionLocal() as db:
        noon = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=12)
        assert run_birthdays(db, now=noon) == 0


def test_csv_export_neutralises_formulas_and_import(client):
    owner = register(client)
    hdr = h(owner)
    client.post("/api/v1/contacts", headers=hdr, json={"name": "=HYPERLINK(\"http://evil\")", "email": "j@example.com"})
    csv_text = client.get("/api/v1/contacts/export.csv", headers=hdr).text
    assert "'=HYPERLINK" in csv_text
    upload = "name,email,phone,birthday,marketing_consent\nKim,kim@example.com,,1992-03-04,yes\n,,,,\nLee,bad-email,,,no\n"
    r = client.post("/api/v1/contacts/import", headers=hdr, files={"file": ("c.csv", upload, "text/csv")})
    assert r.json()["imported"] == 1 and r.json()["skipped"] == 2
