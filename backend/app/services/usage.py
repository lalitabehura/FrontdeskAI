"""Subscription state and monthly usage limits."""
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import Organization, UsageCounter
from app.plans import ACTIVE_STATUSES, plan_for


def period(now: datetime | None = None) -> str:
    return (now or utcnow()).strftime("%Y-%m")


def subscription_active(org: Organization, now: datetime | None = None) -> bool:
    now = now or utcnow()
    if org.subscription_status not in ACTIVE_STATUSES:
        return False
    if org.subscription_status == "trialing" and not org.stripe_subscription_id:
        return bool(org.trial_ends_at and org.trial_ends_at > now)
    return True


def get_counter(db: Session, org_id: str) -> UsageCounter:
    p = period()
    row = db.scalar(select(UsageCounter).where(UsageCounter.org_id == org_id, UsageCounter.period == p))
    if row is None:
        row = UsageCounter(org_id=org_id, period=p, conversations=0, ai_replies=0)
        try:
            with db.begin_nested():
                db.add(row)
        except IntegrityError:  # created concurrently
            row = db.scalar(select(UsageCounter).where(UsageCounter.org_id == org_id, UsageCounter.period == p))
    return row


def conversation_allowed(db: Session, org: Organization) -> tuple[bool, str]:
    if not subscription_active(org):
        return False, "inactive"
    if get_counter(db, org.id).conversations >= plan_for(org.plan).conversations_per_month:
        return False, "limit"
    return True, ""


def bump(db: Session, org_id: str, conversations: int = 0, ai_replies: int = 0) -> None:
    row = get_counter(db, org_id)
    db.execute(update(UsageCounter).where(UsageCounter.id == row.id).values(
        conversations=UsageCounter.conversations + conversations,
        ai_replies=UsageCounter.ai_replies + ai_replies))


def usage_summary(db: Session, org: Organization) -> dict:
    c = get_counter(db, org.id)
    plan = plan_for(org.plan)
    return {"period": c.period, "conversations": c.conversations, "ai_replies": c.ai_replies,
            "conversation_limit": plan.conversations_per_month, "active": subscription_active(org)}