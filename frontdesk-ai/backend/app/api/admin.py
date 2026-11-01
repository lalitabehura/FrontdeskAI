"""Platform-owner console (you, the SaaS operator). Hidden (404) for everyone else."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.db import get_db
from app.deps import require_platform_admin
from app.models import Membership, Organization, UsageCounter, User
from app.plans import PLANS
from app.services import audit
from app.services.usage import period, subscription_active

router = APIRouter(prefix="/admin", tags=["platform admin"])


@router.get("/stats")
def stats(_: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    orgs = db.scalars(select(Organization)).all()
    paying = [o for o in orgs if o.subscription_status in ("active", "past_due") and o.stripe_subscription_id]
    mrr = sum(PLANS[o.plan].price_monthly_usd for o in paying if o.plan in PLANS)
    convs = db.scalar(select(func.coalesce(func.sum(UsageCounter.conversations), 0))
                      .where(UsageCounter.period == period())) or 0
    return {
        "businesses": len(orgs),
        "active": sum(1 for o in orgs if subscription_active(o)),
        "trialing": sum(1 for o in orgs if o.subscription_status == "trialing"),
        "paying": len(paying),
        "mrr_usd": mrr,
        "users": db.scalar(select(func.count()).select_from(User)),
        "signups_7d": sum(1 for o in orgs if o.created_at >= utcnow() - timedelta(days=7)),
        "conversations_this_month": convs,
    }


@router.get("/orgs")
def list_orgs(q: str | None = Query(default=None, max_length=100), _: User = Depends(require_platform_admin),
              db: Session = Depends(get_db)):
    stmt = select(Organization)
    if q:
        stmt = stmt.where(Organization.name.ilike("%" + q.replace("%", "") + "%"))
    out = []
    for o in db.scalars(stmt.order_by(Organization.created_at.desc()).limit(500)).all():
        owner = db.scalar(select(User.email).join(Membership, Membership.user_id == User.id)
                          .where(Membership.org_id == o.id, Membership.role == "owner").limit(1))
        u = db.scalar(select(UsageCounter).where(UsageCounter.org_id == o.id, UsageCounter.period == period()))
        out.append({"id": o.id, "name": o.name, "owner_email": owner, "plan": o.plan,
                    "status": o.subscription_status, "trial_ends_at": o.trial_ends_at, "created_at": o.created_at,
                    "conversations_this_month": u.conversations if u else 0, "active": subscription_active(o)})
    return out


class ExtendTrialIn(BaseModel):
    days: int = Field(ge=1, le=90)


@router.post("/orgs/{org_id}/extend-trial")
def extend_trial(org_id: str, body: ExtendTrialIn, request: Request, admin: User = Depends(require_platform_admin),
                 db: Session = Depends(get_db)):
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Not found")
    base = max(org.trial_ends_at or utcnow(), utcnow())
    org.trial_ends_at = base + timedelta(days=body.days)
    if not org.stripe_subscription_id:
        org.subscription_status = "trialing"
    audit.record(db, "admin.trial_extended", admin.id, request, org_id=org.id, days=body.days)
    db.commit()
    return {"trial_ends_at": org.trial_ends_at}
