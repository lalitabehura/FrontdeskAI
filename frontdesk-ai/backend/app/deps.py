from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token, utcnow
from app.db import get_db
from app.models import Membership, Organization, RefreshToken, User

_bearer = HTTPBearer(auto_error=False)
_UNAUTHORIZED = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated",
                              headers={"WWW-Authenticate": "Bearer"})
ROLE_RANK = {"staff": 1, "admin": 2, "owner": 3}


def get_current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                     db: Session = Depends(get_db)) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _UNAUTHORIZED
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise _UNAUTHORIZED from None
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    if payload["iat"] < int(user.password_changed_at.timestamp()):
        raise _UNAUTHORIZED
    live = db.scalar(select(RefreshToken.id).where(
        RefreshToken.family_id == payload["sid"], RefreshToken.user_id == user.id,
        RefreshToken.revoked_at.is_(None), RefreshToken.expires_at > utcnow()).limit(1))
    if live is None:
        raise _UNAUTHORIZED
    request.state.session_id = payload["sid"]
    request.state.user_id = user.id
    return user


@dataclass
class OrgContext:
    user: User
    org: Organization
    membership: Membership

    @property
    def role(self) -> str:
        return self.membership.role

    @property
    def org_id(self) -> str:
        return self.org.id


def get_org_context(x_org_id: str | None = Header(default=None, max_length=36),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OrgContext:
    """Tenant resolution: the X-Org-Id header selects the org; membership is always verified."""
    stmt = select(Membership).where(Membership.user_id == user.id)
    if x_org_id:
        stmt = stmt.where(Membership.org_id == x_org_id)
    membership = db.scalars(stmt.order_by(Membership.created_at)).first()
    if membership is None:
        raise HTTPException(status_code=404 if x_org_id else 403, detail="Organization not found")
    org = db.get(Organization, membership.org_id)
    return OrgContext(user=user, org=org, membership=membership)


def require_role(min_role: str):
    def dep(ctx: OrgContext = Depends(get_org_context)) -> OrgContext:
        if ROLE_RANK.get(ctx.role, 0) < ROLE_RANK[min_role]:
            raise HTTPException(status_code=403, detail=f"Requires {min_role} role")
        return ctx

    return dep


def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(status_code=404, detail="Not found")
    return user


def require_xhr(request: Request) -> None:
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        raise HTTPException(status_code=403, detail="Missing CSRF header")
