"""Subscriptions via Stripe Checkout + Customer Portal. Webhooks are the source of truth."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import rate_limit
from app.db import get_db
from app.deps import OrgContext, get_org_context, require_role
from app.models import Organization, StripeEvent
from app.plans import PLANS, plan_for
from app.schemas import CheckoutIn
from app.services import audit
from app.services.providers import stripe_billing
from app.services.usage import usage_summary

router = APIRouter(prefix="/billing", tags=["billing"])
log = logging.getLogger("app.billing")


@router.get("")
def billing_overview(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    org = ctx.org
    return {
        "enabled": stripe_billing.enabled(),
        "plan": org.plan, "status": org.subscription_status, "trial_ends_at": org.trial_ends_at,
        "current_period_end": org.current_period_end, "has_subscription": bool(org.stripe_subscription_id),
        "usage": usage_summary(db, org),
        "plans": [{"key": p.key, "name": p.name, "price": p.price_monthly_usd,
                   "conversations": p.conversations_per_month, "members": p.max_members, "features": list(p.features)}
                  for p in PLANS.values()],
    }


@router.post("/checkout", dependencies=[Depends(rate_limit("checkout", 10, 300))])
def checkout(body: CheckoutIn, request: Request, ctx: OrgContext = Depends(require_role("owner")),
             db: Session = Depends(get_db)):
    if not stripe_billing.enabled():
        raise HTTPException(status_code=400, detail="Billing is not configured on this server.")
    plan = PLANS[body.plan]
    if not plan.stripe_price_id:
        raise HTTPException(status_code=400, detail="This plan has no Stripe price configured.")
    org = ctx.org
    if org.stripe_subscription_id and org.subscription_status in ("active", "trialing", "past_due"):
        raise HTTPException(status_code=409, detail="You already have a subscription. Use 'Manage billing' to change plans.")
    front = get_settings().frontend_url
    try:
        if not org.stripe_customer_id:
            org.stripe_customer_id = stripe_billing.create_customer(ctx.user.email, org.id, org.name)
            db.commit()
        url = stripe_billing.create_checkout(org.stripe_customer_id, plan.stripe_price_id, org.id,
                                             f"{front}/billing?checkout=success", f"{front}/billing?checkout=cancelled")
    except stripe_billing.BillingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    audit.record(db, "billing.checkout_started", ctx.user.id, request, org_id=org.id, plan=body.plan)
    db.commit()
    return {"url": url}


@router.post("/portal", dependencies=[Depends(rate_limit("portal", 10, 300))])
def portal(ctx: OrgContext = Depends(require_role("owner"))):
    if not stripe_billing.enabled() or not ctx.org.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account yet.")
    try:
        return {"url": stripe_billing.create_portal(ctx.org.stripe_customer_id, f"{get_settings().frontend_url}/billing")}
    except stripe_billing.BillingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


def _plan_from_price(price_id: str | None) -> str | None:
    for p in PLANS.values():
        if p.stripe_price_id and p.stripe_price_id == price_id:
            return p.key
    return None


def _apply_subscription(db: Session, sub: dict) -> None:
    org_id = (sub.get("metadata") or {}).get("org_id")
    org = db.get(Organization, org_id) if org_id else None
    if org is None and sub.get("customer"):
        org = db.scalar(select(Organization).where(Organization.stripe_customer_id == sub["customer"]))
    if org is None:
        log.warning("subscription event for unknown org")
        return
    items = (sub.get("items") or {}).get("data") or []
    price_id = items[0]["price"]["id"] if items else None
    org.plan = _plan_from_price(price_id) or plan_for(org.plan).key
    org.subscription_status = sub.get("status", org.subscription_status)
    org.stripe_subscription_id = sub.get("id")
    org.stripe_customer_id = sub.get("customer") or org.stripe_customer_id
    period_end = sub.get("current_period_end") or (items[0].get("current_period_end") if items else None)
    if period_end:
        org.current_period_end = datetime.fromtimestamp(int(period_end), tz=timezone.utc)
    if sub.get("status") == "canceled":
        org.stripe_subscription_id = None
    audit.record(db, "billing.subscription_updated", None, None, org_id=org.id, status=org.subscription_status,
                 plan=org.plan)


@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, stripe_signature: str | None = Header(default=None, max_length=1000),
                  db: Session = Depends(get_db)):
    secret = get_settings().stripe_webhook_secret
    if not secret:
        raise HTTPException(status_code=404, detail="Not found")
    payload = await request.body()
    try:
        event = stripe_billing.verify_webhook(payload, stripe_signature or "", secret)
    except stripe_billing.BillingError:
        raise HTTPException(status_code=400, detail="Invalid signature") from None
    try:  # idempotency: Stripe retries deliveries
        db.add(StripeEvent(id=str(event["id"])[:80], type=str(event.get("type"))[:80]))
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"received": True, "duplicate": True}
    obj = (event.get("data") or {}).get("object") or {}
    etype = event.get("type", "")
    if etype.startswith("customer.subscription."):
        _apply_subscription(db, obj)
    elif etype == "checkout.session.completed" and obj.get("client_reference_id"):
        org = db.get(Organization, obj["client_reference_id"])
        if org and obj.get("customer"):
            org.stripe_customer_id = obj["customer"]
            org.stripe_subscription_id = obj.get("subscription") or org.stripe_subscription_id
            org.subscription_status = "active"
    elif etype == "invoice.payment_failed" and obj.get("customer"):
        org = db.scalar(select(Organization).where(Organization.stripe_customer_id == obj["customer"]))
        if org:
            org.subscription_status = "past_due"
    db.commit()
    return {"received": True}
