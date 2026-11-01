"""Organization lifecycle helpers."""
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import utcnow
from app.models import DEFAULT_HOURS, AssistantConfig, Membership, Organization, Service, User
from app.plans import TRIAL_PLAN


def new_widget_key() -> str:
    return "wk_" + secrets.token_urlsafe(24)


def create_org(db: Session, owner: User, name: str, timezone: str = "UTC") -> Organization:
    org = Organization(name=name.strip(), timezone=timezone, plan=TRIAL_PLAN, subscription_status="trialing",
                       trial_ends_at=utcnow() + timedelta(days=get_settings().trial_days))
    db.add(org)
    db.flush()
    db.add(Membership(org_id=org.id, user_id=owner.id, role="owner"))
    db.add(AssistantConfig(org_id=org.id, widget_key=new_widget_key(), hours=dict(DEFAULT_HOURS),
                           notify_email=owner.email, contact_email=owner.email,
                           greeting=f"Hi! 👋 Welcome to {org.name}. How can I help you today?"))
    db.add(Service(org_id=org.id, name="Consultation", description="An initial consultation.",
                   duration_minutes=30, price_text="Free"))
    db.flush()
    return org
