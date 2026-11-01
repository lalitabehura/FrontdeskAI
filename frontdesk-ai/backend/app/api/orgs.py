"""Organizations (tenants), team members and invitations."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.auth import accept_invitation
from app.core.config import get_settings
from app.core.rate_limit import rate_limit
from app.core.security import hash_token, new_opaque_token, utcnow, verify_password
from app.db import get_db
from app.deps import ROLE_RANK, OrgContext, get_current_user, get_org_context, require_role
from app.models import ORG_OWNED_MODELS, AuditLog, Invitation, Membership, Organization, User
from app.plans import plan_for
from app.schemas import (
    AcceptInviteIn,
    InviteCreated,
    InviteIn,
    InviteOut,
    MemberOut,
    OrgCreate,
    OrgOut,
    OrgUpdate,
    OrgWithRole,
    RoleIn,
)
from app.services import audit
from app.services.mailer import send_email
from app.services.providers import stripe_billing
from app.services.tenancy import create_org

router = APIRouter(tags=["organizations"])


@router.get("/orgs", response_model=list[OrgWithRole])
def my_orgs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Organization, Membership.role).join(Membership, Membership.org_id == Organization.id)
                      .where(Membership.user_id == user.id).order_by(Membership.created_at)).all()
    return [OrgWithRole(**OrgOut.model_validate(o).model_dump(), role=r) for o, r in rows]


@router.post("/orgs", response_model=OrgWithRole, status_code=201,
             dependencies=[Depends(rate_limit("org_create", 5, 3600))])
def new_org(body: OrgCreate, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owned = db.scalar(select(func.count()).select_from(Membership).where(
        Membership.user_id == user.id, Membership.role == "owner"))
    if owned >= 10:
        raise HTTPException(status_code=400, detail="You can own at most 10 businesses.")
    org = create_org(db, user, body.name, body.timezone)
    audit.record(db, "org.created", user.id, request, org_id=org.id)
    db.commit()
    return OrgWithRole(**OrgOut.model_validate(org).model_dump(), role="owner")


@router.get("/org", response_model=OrgWithRole)
def current_org(ctx: OrgContext = Depends(get_org_context)):
    return OrgWithRole(**OrgOut.model_validate(ctx.org).model_dump(), role=ctx.role)


@router.patch("/org", response_model=OrgOut)
def update_org(body: OrgUpdate, request: Request, ctx: OrgContext = Depends(require_role("admin")),
               db: Session = Depends(get_db)):
    for k, v in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(ctx.org, k, v.strip() if isinstance(v, str) else v)
    audit.record(db, "org.updated", ctx.user.id, request, org_id=ctx.org_id)
    db.commit()
    return ctx.org


class DeleteOrgIn(BaseModel):
    password: str = Field(max_length=128)
    confirm_name: str = Field(max_length=120)


@router.delete("/org", status_code=204, dependencies=[Depends(rate_limit("org_delete", 5, 3600))])
def delete_org(body: DeleteOrgIn, request: Request, ctx: OrgContext = Depends(require_role("owner")),
               db: Session = Depends(get_db)):
    if not verify_password(ctx.user.password_hash, body.password):
        raise HTTPException(status_code=400, detail="Password is incorrect.")
    if body.confirm_name.strip() != ctx.org.name:
        raise HTTPException(status_code=400, detail="Business name does not match.")
    purge_org(db, ctx.org)
    audit.record(db, "org.deleted", ctx.user.id, request, org_id=ctx.org_id)
    db.commit()


def purge_org(db: Session, org: Organization) -> None:
    if org.stripe_subscription_id:
        stripe_billing.cancel_subscription(org.stripe_subscription_id)
    for model in ORG_OWNED_MODELS:
        db.execute(delete(model).where(model.org_id == org.id))
    db.execute(delete(AuditLog).where(AuditLog.org_id == org.id))
    db.delete(org)


# --------------------------------------------------------------------------- members
@router.get("/org/members", response_model=list[MemberOut])
def members(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    rows = db.execute(select(Membership, User).join(User, User.id == Membership.user_id)
                      .where(Membership.org_id == ctx.org_id).order_by(Membership.created_at)).all()
    return [MemberOut(id=m.id, user_id=u.id, email=u.email, full_name=u.full_name, role=m.role,
                      created_at=m.created_at) for m, u in rows]


def _owned_member(db: Session, ctx: OrgContext, member_id: str) -> Membership:
    m = db.get(Membership, member_id)
    if m is None or m.org_id != ctx.org_id:
        raise HTTPException(status_code=404, detail="Member not found")
    return m


def _owner_count(db: Session, org_id: str) -> int:
    return db.scalar(select(func.count()).select_from(Membership).where(
        Membership.org_id == org_id, Membership.role == "owner"))


@router.patch("/org/members/{member_id}", response_model=MemberOut)
def change_role(member_id: str, body: RoleIn, request: Request, ctx: OrgContext = Depends(require_role("admin")),
                db: Session = Depends(get_db)):
    m = _owned_member(db, ctx, member_id)
    # Admins can't create/demote owners or modify someone at/above their own rank.
    if ctx.role != "owner" and (body.role == "owner" or ROLE_RANK[m.role] >= ROLE_RANK[ctx.role]):
        raise HTTPException(status_code=403, detail="Only an owner can do that.")
    if m.role == "owner" and body.role != "owner" and _owner_count(db, ctx.org_id) <= 1:
        raise HTTPException(status_code=400, detail="A business must keep at least one owner.")
    m.role = body.role
    audit.record(db, "member.role_changed", ctx.user.id, request, org_id=ctx.org_id, member=m.user_id, role=body.role)
    db.commit()
    u = db.get(User, m.user_id)
    return MemberOut(id=m.id, user_id=u.id, email=u.email, full_name=u.full_name, role=m.role, created_at=m.created_at)


@router.delete("/org/members/{member_id}", status_code=204)
def remove_member(member_id: str, request: Request, ctx: OrgContext = Depends(get_org_context),
                  db: Session = Depends(get_db)):
    m = _owned_member(db, ctx, member_id)
    leaving_self = m.user_id == ctx.user.id
    if not leaving_self:
        if ctx.role == "staff" or (ctx.role == "admin" and m.role in ("admin", "owner")):
            raise HTTPException(status_code=403, detail="You can't remove this member.")
    if m.role == "owner" and _owner_count(db, ctx.org_id) <= 1:
        raise HTTPException(status_code=400, detail="Transfer ownership before the last owner leaves.")
    db.delete(m)
    audit.record(db, "member.removed", ctx.user.id, request, org_id=ctx.org_id, member=m.user_id)
    db.commit()


# --------------------------------------------------------------------------- invitations
@router.get("/org/invitations", response_model=list[InviteOut])
def list_invites(ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return db.scalars(select(Invitation).where(Invitation.org_id == ctx.org_id, Invitation.accepted_at.is_(None),
                                               Invitation.expires_at > utcnow())
                      .order_by(Invitation.created_at.desc())).all()


@router.post("/org/invitations", response_model=InviteCreated, status_code=201,
             dependencies=[Depends(rate_limit("invite", 20, 3600))])
def invite(body: InviteIn, request: Request, ctx: OrgContext = Depends(require_role("admin")),
           db: Session = Depends(get_db)):
    s = get_settings()
    email = body.email.lower()
    plan = plan_for(ctx.org.plan)
    members_n = db.scalar(select(func.count()).select_from(Membership).where(Membership.org_id == ctx.org_id))
    pending_n = db.scalar(select(func.count()).select_from(Invitation).where(
        Invitation.org_id == ctx.org_id, Invitation.accepted_at.is_(None), Invitation.expires_at > utcnow()))
    if members_n + pending_n >= plan.max_members:
        raise HTTPException(status_code=402, detail=f"Your {plan.name} plan allows {plan.max_members} team members.")
    if db.scalar(select(Membership.id).join(User, User.id == Membership.user_id)
                 .where(Membership.org_id == ctx.org_id, User.email == email)):
        raise HTTPException(status_code=409, detail="That person is already a member.")
    raw = new_opaque_token()
    inv = Invitation(org_id=ctx.org_id, email=email, role=body.role, token_hash=hash_token(raw),
                     invited_by=ctx.user.id, expires_at=utcnow() + timedelta(days=s.invitation_ttl_days))
    db.add(inv)
    audit.record(db, "member.invited", ctx.user.id, request, org_id=ctx.org_id, email=email)
    db.commit()
    url = f"{s.frontend_url}/invite#token={raw}"
    send_email(email, f"You're invited to join {ctx.org.name} on {s.app_name}",
               f"{ctx.user.full_name or ctx.user.email} invited you to help manage {ctx.org.name}'s AI assistant.\n\n"
               f"Accept within {s.invitation_ttl_days} days:\n{url}")
    return InviteCreated(**InviteOut.model_validate(inv).model_dump(), invite_url=url)


@router.delete("/org/invitations/{invite_id}", status_code=204)
def revoke_invite(invite_id: str, ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db)):
    inv = db.get(Invitation, invite_id)
    if inv is None or inv.org_id != ctx.org_id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    db.delete(inv)
    db.commit()


@router.post("/invitations/accept", response_model=OrgWithRole)
def accept(body: AcceptInviteIn, request: Request, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    m = accept_invitation(db, user, body.token)
    audit.record(db, "member.joined", user.id, request, org_id=m.org_id)
    db.commit()
    org = db.get(Organization, m.org_id)
    return OrgWithRole(**OrgOut.model_validate(org).model_dump(), role=m.role)


# --------------------------------------------------------------------------- account deletion
class DeleteAccountIn(BaseModel):
    password: str = Field(max_length=128)
    confirm: str = Field(pattern="^DELETE$")


@router.delete("/account", status_code=204, dependencies=[Depends(rate_limit("delete_account", 5, 3600))])
def delete_account(body: DeleteAccountIn, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    if not verify_password(user.password_hash, body.password):
        raise HTTPException(status_code=400, detail="Password is incorrect.")
    for m in db.scalars(select(Membership).where(Membership.user_id == user.id)).all():
        others = db.scalar(select(func.count()).select_from(Membership).where(
            Membership.org_id == m.org_id, Membership.user_id != user.id))
        if m.role == "owner" and others and _owner_count(db, m.org_id) <= 1:
            org = db.get(Organization, m.org_id)
            raise HTTPException(status_code=400, detail=f"Transfer ownership of '{org.name}' before deleting your account.")
        if not others:
            purge_org(db, db.get(Organization, m.org_id))
    db.execute(delete(Membership).where(Membership.user_id == user.id))
    db.execute(delete(AuditLog).where(AuditLog.user_id == user.id))
    db.delete(user)
    audit.record(db, "account.deleted", None, request)
    db.commit()


@router.get("/org/audit-log")
def org_audit(limit: int = Query(default=100, ge=1, le=500), ctx: OrgContext = Depends(require_role("admin")),
              db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).where(AuditLog.org_id == ctx.org_id)
                      .order_by(AuditLog.created_at.desc()).limit(limit)).all()
    return [{"id": r.id, "action": r.action, "user_id": r.user_id, "ip": r.ip, "meta": r.meta,
             "created_at": r.created_at} for r in rows]
