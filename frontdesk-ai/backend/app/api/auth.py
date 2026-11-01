"""Authentication: registration (+ business creation or invite acceptance), login (+MFA),
refresh-token rotation with reuse detection, sessions, password flows."""
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import client_ip, rate_limit
from app.core.security import (
    create_access_token,
    dummy_verify,
    hash_password,
    hash_token,
    new_opaque_token,
    new_recovery_codes,
    new_totp_secret,
    password_needs_rehash,
    totp_uri,
    utcnow,
    validate_password_strength,
    verify_password,
    verify_totp,
)
from app.db import get_db
from app.deps import get_current_user, require_xhr
from app.models import Invitation, Membership, PasswordResetToken, RefreshToken, User
from app.schemas import (
    LoginIn,
    MfaCodeIn,
    MfaDisableIn,
    MfaSetupOut,
    PasswordChangeIn,
    PasswordForgotIn,
    PasswordResetIn,
    ProfileIn,
    RecoveryCodesOut,
    RegisterIn,
    SessionOut,
    TokenOut,
    UserOut,
)
from app.services import audit
from app.services.mailer import send_system_email
from app.services.tenancy import create_org

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "fd_rt"
COOKIE_PATH = "/api/v1/auth"
_GENERIC_LOGIN_ERROR = "Invalid email or password."


def _set_refresh_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(REFRESH_COOKIE, token, max_age=s.refresh_token_ttl_days * 86400, httponly=True,
                        secure=s.is_production, samesite="strict", path=COOKIE_PATH)


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)


def _issue_session(db: Session, user: User, request: Request, response: Response,
                   family_id: str | None = None) -> tuple[TokenOut, RefreshToken]:
    s = get_settings()
    raw = new_opaque_token()
    row = RefreshToken(user_id=user.id, family_id=family_id or str(uuid.uuid4()), token_hash=hash_token(raw),
                       expires_at=utcnow() + timedelta(days=s.refresh_token_ttl_days),
                       user_agent=request.headers.get("user-agent", "")[:300], ip=client_ip(request))
    db.add(row)
    db.flush()
    access, ttl = create_access_token(user.id, row.family_id)
    _set_refresh_cookie(response, raw)
    return TokenOut(access_token=access, expires_in=ttl, user=UserOut.model_validate(user)), row


def _revoke_family(db: Session, family_id: str) -> None:
    db.execute(update(RefreshToken).where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=utcnow()))


def _revoke_all(db: Session, user_id: str) -> None:
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=utcnow()))


def _sync_admin_flag(user: User) -> None:
    if user.email in get_settings().admin_emails:
        user.is_platform_admin = True


def accept_invitation(db: Session, user: User, raw_token: str) -> Membership:
    inv = db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(raw_token)))
    if inv is None or inv.accepted_at is not None or inv.expires_at <= utcnow():
        raise HTTPException(status_code=400, detail="This invitation is invalid or has expired.")
    if inv.email.lower() != user.email.lower():
        raise HTTPException(status_code=403, detail="This invitation was sent to a different email address.")
    existing = db.scalar(select(Membership).where(Membership.org_id == inv.org_id, Membership.user_id == user.id))
    inv.accepted_at = utcnow()
    if existing:
        return existing
    m = Membership(org_id=inv.org_id, user_id=user.id, role=inv.role)
    db.add(m)
    db.flush()
    return m


# --------------------------------------------------------------------------- register / login
@router.post("/register", response_model=TokenOut, status_code=201,
             dependencies=[Depends(rate_limit("register", 5, 3600))])
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    try:
        validate_password_strength(body.password, email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(email=email, password_hash=hash_password(body.password), full_name=body.full_name.strip())
    _sync_admin_flag(user)
    db.add(user)
    db.flush()
    if body.invite_token:
        m = accept_invitation(db, user, body.invite_token)
        audit.record(db, "auth.register_invited", user.id, request, org_id=m.org_id)
    else:
        org = create_org(db, user, body.business_name or "", body.timezone)
        audit.record(db, "auth.register", user.id, request, org_id=org.id)
    out, _ = _issue_session(db, user, request, response)
    db.commit()
    return out


@router.post("/login", response_model=TokenOut, dependencies=[Depends(rate_limit("login", 10, 60))])
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active:
        dummy_verify(body.password)
        audit.record(db, "auth.login_failed", None, request, reason="unknown_email")
        db.commit()
        raise HTTPException(status_code=401, detail=_GENERIC_LOGIN_ERROR)
    now = utcnow()
    if user.locked_until and user.locked_until > now:
        dummy_verify(body.password)
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")
    if not verify_password(user.password_hash, body.password):
        user.failed_logins += 1
        if user.failed_logins >= s.max_failed_logins:
            user.locked_until = now + timedelta(minutes=s.lockout_minutes)
            user.failed_logins = 0
            audit.record(db, "auth.locked", user.id, request)
        audit.record(db, "auth.login_failed", user.id, request, reason="bad_password")
        db.commit()
        raise HTTPException(status_code=401, detail=_GENERIC_LOGIN_ERROR)
    if user.mfa_enabled:
        if body.mfa_code:
            counter = verify_totp(user.mfa_secret or "", body.mfa_code, user.mfa_last_counter)
            if counter is None:
                audit.record(db, "auth.mfa_failed", user.id, request)
                db.commit()
                raise HTTPException(status_code=401, detail="Invalid verification code.")
            user.mfa_last_counter = counter
        elif body.recovery_code:
            h = hash_token(body.recovery_code.strip().lower())
            if h not in (user.recovery_code_hashes or []):
                audit.record(db, "auth.recovery_failed", user.id, request)
                db.commit()
                raise HTTPException(status_code=401, detail="Invalid recovery code.")
            user.recovery_code_hashes = [c for c in user.recovery_code_hashes if c != h]
            audit.record(db, "auth.recovery_used", user.id, request)
        else:
            raise HTTPException(status_code=401, detail="mfa_required")
    user.failed_logins = 0
    user.locked_until = None
    _sync_admin_flag(user)
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    out, _ = _issue_session(db, user, request, response)
    audit.record(db, "auth.login", user.id, request)
    db.commit()
    return out


@router.post("/refresh", response_model=TokenOut,
             dependencies=[Depends(require_xhr), Depends(rate_limit("refresh", 30, 60))])
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="No session")
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    if row is None:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Invalid session")
    if row.revoked_at is not None:
        _revoke_family(db, row.family_id)  # reuse of a rotated token => likely theft
        audit.record(db, "auth.refresh_reuse_detected", row.user_id, request)
        db.commit()
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Session revoked")
    if row.expires_at <= utcnow():
        raise HTTPException(status_code=401, detail="Session expired")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid session")
    row.revoked_at = utcnow()
    out, new_row = _issue_session(db, user, request, response, family_id=row.family_id)
    row.replaced_by = new_row.id
    db.commit()
    return out


@router.post("/logout", status_code=204, dependencies=[Depends(require_xhr)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
        if row:
            _revoke_family(db, row.family_id)
            audit.record(db, "auth.logout", row.user_id, request)
            db.commit()
    _clear_refresh_cookie(response)


@router.post("/logout-all", status_code=204)
def logout_all(request: Request, response: Response, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    _revoke_all(db, user.id)
    audit.record(db, "auth.logout_all", user.id, request)
    db.commit()
    _clear_refresh_cookie(response)


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(RefreshToken).where(
        RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None), RefreshToken.expires_at > utcnow(),
    ).order_by(RefreshToken.created_at.desc())).all()
    return [SessionOut(id=r.family_id, created_at=r.created_at, user_agent=r.user_agent, ip=r.ip,
                       current=r.family_id == request.state.session_id) for r in rows]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(session_id: str, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    owned = db.scalar(select(RefreshToken.id).where(RefreshToken.family_id == session_id,
                                                    RefreshToken.user_id == user.id).limit(1))
    if not owned:
        raise HTTPException(status_code=404, detail="Session not found")
    _revoke_family(db, session_id)
    audit.record(db, "auth.session_revoked", user.id, request)
    db.commit()


# --------------------------------------------------------------------------- password flows
@router.post("/password/forgot", status_code=202, dependencies=[Depends(rate_limit("forgot", 5, 3600))])
def forgot_password(body: PasswordForgotIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user and user.is_active:
        raw = new_opaque_token()
        db.add(PasswordResetToken(user_id=user.id, token_hash=hash_token(raw),
                                  expires_at=utcnow() + timedelta(minutes=s.password_reset_ttl_minutes)))
        audit.record(db, "auth.password_reset_requested", user.id, request)
        db.commit()
        send_system_email(user.email, f"Reset your {s.app_name} password",
                          f"Use this link within {s.password_reset_ttl_minutes} minutes:\n"
                          f"{s.frontend_url}/reset-password#token={raw}\n\nIf you did not request this, ignore this email.")
    return {"detail": "If that account exists, a reset link has been sent."}


@router.post("/password/reset", status_code=204, dependencies=[Depends(rate_limit("reset", 10, 3600))])
def reset_password(body: PasswordResetIn, request: Request, db: Session = Depends(get_db)):
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(body.token)))
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset link.")
    user = db.get(User, row.user_id)
    try:
        validate_password_strength(body.new_password, user.email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    row.used_at = utcnow()
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = utcnow()
    user.failed_logins, user.locked_until = 0, None
    _revoke_all(db, user.id)
    audit.record(db, "auth.password_reset", user.id, request)
    db.commit()


@router.post("/password/change", status_code=204)
def change_password(body: PasswordChangeIn, request: Request, response: Response,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    try:
        validate_password_strength(body.new_password, user.email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = utcnow()
    _revoke_all(db, user.id)
    audit.record(db, "auth.password_changed", user.id, request)
    db.commit()
    _clear_refresh_cookie(response)


# --------------------------------------------------------------------------- MFA
@router.post("/mfa/setup", response_model=MfaSetupOut)
def mfa_setup(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled.")
    secret = new_totp_secret()
    user.mfa_secret = secret
    db.commit()
    return MfaSetupOut(secret=secret, otpauth_uri=totp_uri(secret, user.email, get_settings().app_name))


@router.post("/mfa/enable", response_model=RecoveryCodesOut, dependencies=[Depends(rate_limit("mfa", 10, 300))])
def mfa_enable(body: MfaCodeIn, request: Request, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    if user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(status_code=400, detail="Start MFA setup first.")
    counter = verify_totp(user.mfa_secret, body.code, user.mfa_last_counter)
    if counter is None:
        raise HTTPException(status_code=400, detail="Invalid code. Check your device clock.")
    codes = new_recovery_codes()
    user.mfa_enabled, user.mfa_last_counter = True, counter
    user.recovery_code_hashes = [hash_token(c) for c in codes]
    audit.record(db, "auth.mfa_enabled", user.id, request)
    db.commit()
    return RecoveryCodesOut(recovery_codes=codes)


@router.post("/mfa/disable", status_code=204, dependencies=[Depends(rate_limit("mfa", 10, 300))])
def mfa_disable(body: MfaDisableIn, request: Request, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    if not user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled.")
    if not verify_password(user.password_hash, body.password):
        raise HTTPException(status_code=400, detail="Password is incorrect.")
    if verify_totp(user.mfa_secret or "", body.code, user.mfa_last_counter) is None:
        raise HTTPException(status_code=400, detail="Invalid code.")
    user.mfa_enabled, user.mfa_secret, user.recovery_code_hashes = False, None, []
    audit.record(db, "auth.mfa_disabled", user.id, request)
    db.commit()


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(body: ProfileIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.full_name = body.full_name.strip()
    db.commit()
    return user
