"""Minimal Stripe client (Checkout, Customer Portal, webhooks) over HTTPS - no SDK needed."""
import hashlib
import hmac
import json
import logging
import time

import httpx

from app.core.config import get_settings

log = logging.getLogger("app.stripe")
API = "https://api.stripe.com/v1"
_TIMEOUT = httpx.Timeout(20.0)


class BillingError(Exception):
    pass


def enabled() -> bool:
    return bool(get_settings().stripe_secret_key)


def _post(path: str, data: dict) -> dict:
    s = get_settings()
    r = httpx.post(f"{API}{path}", data=data, auth=(s.stripe_secret_key or "", ""), timeout=_TIMEOUT)
    if r.status_code >= 400:
        log.warning("stripe error %s on %s", r.status_code, path)
        raise BillingError("Payment provider error. Please try again.")
    return r.json()


def create_customer(email: str, org_id: str, name: str) -> str:
    return _post("/customers", {"email": email, "name": name, "metadata[org_id]": org_id})["id"]


def create_checkout(customer_id: str, price_id: str, org_id: str, success_url: str, cancel_url: str) -> str:
    data = {
        "mode": "subscription",
        "customer": customer_id,
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "client_reference_id": org_id,
        "subscription_data[metadata][org_id]": org_id,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "allow_promotion_codes": "true",
    }
    return _post("/checkout/sessions", data)["url"]


def create_portal(customer_id: str, return_url: str) -> str:
    return _post("/billing_portal/sessions", {"customer": customer_id, "return_url": return_url})["url"]


def cancel_subscription(subscription_id: str) -> None:
    if not enabled():
        return
    s = get_settings()
    try:
        httpx.delete(f"{API}/subscriptions/{subscription_id}", auth=(s.stripe_secret_key or "", ""), timeout=_TIMEOUT)
    except httpx.HTTPError:
        log.warning("could not cancel subscription %s", subscription_id)


def verify_webhook(payload: bytes, sig_header: str, secret: str, tolerance: int = 300) -> dict:
    """Implements Stripe's signature scheme: HMAC-SHA256 over '{timestamp}.{payload}'."""
    try:
        parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
        timestamp = int(parts["t"])
        signatures = [v for k, v in (p.split("=", 1) for p in sig_header.split(",") if "=" in p) if k == "v1"]
    except (KeyError, ValueError):
        raise BillingError("Malformed signature header") from None
    if abs(time.time() - timestamp) > tolerance:
        raise BillingError("Signature timestamp outside tolerance")
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in signatures):
        raise BillingError("Invalid signature")
    return json.loads(payload)
