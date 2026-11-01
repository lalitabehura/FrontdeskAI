"""Public API used by the embeddable chat widget. No user login: visitors hold a per-conversation
token (stored hashed). Heavily rate limited; tenant resolved from the public widget key."""
from datetime import date
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import client_ip, limiter
from app.core.security import constant_time_equals, hash_token, new_opaque_token, utcnow
from app.db import get_db
from app.models import AssistantConfig, Contact, Conversation, ConversationMessage, Organization, Service
from app.schemas import PublicBookIn, PublicContactIn, PublicMessageIn, PublicStartIn
from app.services import booking as booking_svc
from app.services import engine, usage
from app.services.background import in_new_session, notify_booking, notify_handoff, notify_lead
from app.services.notify import unsubscribe_sig

router = APIRouter(prefix="/public", tags=["public widget"])


def _limit(request: Request, name: str, limit: int, window: int) -> None:
    if not limiter.hit(f"pub:{name}:{client_ip(request)}", limit, window):
        raise HTTPException(status_code=429, detail="You're sending messages too quickly. Please wait a moment.",
                            headers={"Retry-After": str(window)})


def _org_by_key(db: Session, key: str) -> tuple[Organization, AssistantConfig]:
    cfg = db.scalar(select(AssistantConfig).where(AssistantConfig.widget_key == key)) if len(key) <= 48 else None
    if cfg is None:
        raise HTTPException(status_code=404, detail="Assistant not found")
    return db.get(Organization, cfg.org_id), cfg


def _visitor_conversation(db: Session, conversation_id: str, token: str | None) -> Conversation:
    conv = db.get(Conversation, conversation_id) if len(conversation_id) <= 36 else None
    if conv is None or not token or not constant_time_equals(conv.visitor_token_hash, hash_token(token)):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


def _msg(m: ConversationMessage) -> dict:
    return {"id": m.id, "role": "assistant" if m.role in ("assistant", "system") else m.role,
            "content": m.content, "created_at": m.created_at.isoformat()}


def _add(db: Session, conv: Conversation, role: str, content: str) -> ConversationMessage:
    m = ConversationMessage(org_id=conv.org_id, conversation_id=conv.id, role=role, content=content)
    db.add(m)
    conv.message_count += 1
    conv.last_message_at = utcnow()
    db.flush()
    return m


def _unavailable_text(cfg: AssistantConfig) -> str:
    contact = " or ".join(x for x in (cfg.contact_phone, cfg.contact_email) if x)
    return "Our chat assistant is unavailable right now." + (f" Please contact us at {contact}." if contact else "")


# --------------------------------------------------------------------------- config & start
@router.get("/{key}/config")
def widget_config(key: str, request: Request, db: Session = Depends(get_db)):
    _limit(request, "config", 60, 60)
    org, cfg = _org_by_key(db, key)
    services = db.scalars(select(Service).where(Service.org_id == org.id, Service.active.is_(True))
                          .order_by(Service.sort_order, Service.name)).all()
    available = cfg.enabled and usage.subscription_active(org)
    return {
        "business_name": org.name, "assistant_name": cfg.assistant_name, "greeting": cfg.greeting,
        "brand_color": cfg.brand_color, "position": cfg.position, "timezone": org.timezone,
        "available": available, "unavailable_message": None if available else _unavailable_text(cfg),
        "booking_enabled": cfg.booking_enabled, "require_phone": cfg.require_phone,
        "birthday_enabled": cfg.birthday_enabled and org.plan != "starter",
        "services": [{"id": s.id, "name": s.name, "duration_minutes": s.duration_minutes, "price_text": s.price_text}
                     for s in services if s.bookable],
    }


@router.post("/{key}/conversations")
def start_conversation(key: str, body: PublicStartIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    _limit(request, "start", s.widget_conversations_per_hour, 3600)
    org, cfg = _org_by_key(db, key)
    allowed, reason = usage.conversation_allowed(db, org)
    if not cfg.enabled or not allowed:
        return {"conversation_id": None, "unavailable": True, "message": _unavailable_text(cfg), "reason": reason}
    raw = new_opaque_token()
    conv = Conversation(org_id=org.id, visitor_token_hash=hash_token(raw), page_url=body.page_url[:500],
                        ip=client_ip(request))
    db.add(conv)
    db.flush()
    greeting = _add(db, conv, "assistant", cfg.greeting)
    usage.bump(db, org.id, conversations=1)
    db.commit()
    return {"conversation_id": conv.id, "token": raw, "messages": [_msg(greeting)]}


# --------------------------------------------------------------------------- messages
@router.get("/conversations/{conversation_id}/messages")
def poll_messages(conversation_id: str, request: Request, after_id: int = Query(default=0, ge=0),
                  x_visitor_token: str | None = Header(default=None, max_length=100), db: Session = Depends(get_db)):
    _limit(request, "poll", 40, 60)
    conv = _visitor_conversation(db, conversation_id, x_visitor_token)
    rows = db.scalars(select(ConversationMessage).where(
        ConversationMessage.conversation_id == conv.id, ConversationMessage.id > after_id)
        .order_by(ConversationMessage.id).limit(100)).all()
    return {"messages": [_msg(m) for m in rows], "status": conv.status}


@router.post("/conversations/{conversation_id}/messages")
def send_message(conversation_id: str, body: PublicMessageIn, request: Request, background: BackgroundTasks,
                 x_visitor_token: str | None = Header(default=None, max_length=100), db: Session = Depends(get_db)):
    s = get_settings()
    _limit(request, "msg", s.widget_messages_per_minute, 60)
    conv = _visitor_conversation(db, conversation_id, x_visitor_token)
    if conv.message_count >= s.max_messages_per_conversation:
        raise HTTPException(status_code=429, detail="This conversation is very long — please leave your contact "
                                                    "details and our team will follow up.")
    org = db.get(Organization, conv.org_id)
    cfg = db.get(AssistantConfig, conv.org_id)
    if not cfg.enabled or not usage.subscription_active(org):
        raise HTTPException(status_code=503, detail=_unavailable_text(cfg))
    visitor = _add(db, conv, "visitor", body.content.strip())
    if conv.status == "closed":
        conv.status = "ai"
    if conv.status == "human":
        conv.needs_attention = True
        db.commit()
        return {"messages": [_msg(visitor)], "action": None, "waiting_for_human": True}

    history = [(m.role, m.content) for m in db.scalars(
        select(ConversationMessage).where(ConversationMessage.conversation_id == conv.id,
                                          ConversationMessage.id < visitor.id)
        .order_by(ConversationMessage.id.desc()).limit(16)).all()][::-1]
    ctx = engine.load_context(db, org, cfg)
    out = engine.respond(ctx, history, body.content.strip())
    reply = _add(db, conv, "assistant", out.reply)
    if out.used_ai:
        usage.bump(db, org.id, ai_replies=1)
    if out.needs_human:
        conv.needs_attention = True
        if out.action == "handoff":
            background.add_task(in_new_session, notify_handoff, org.id, conv.id, body.content[:500])
    db.commit()
    return {"messages": [_msg(visitor), _msg(reply)], "action": out.action, "waiting_for_human": False}


# --------------------------------------------------------------------------- lead capture
@router.post("/conversations/{conversation_id}/contact")
def leave_contact(conversation_id: str, body: PublicContactIn, request: Request, background: BackgroundTasks,
                  x_visitor_token: str | None = Header(default=None, max_length=100), db: Session = Depends(get_db)):
    _limit(request, "contact", 10, 600)
    conv = _visitor_conversation(db, conversation_id, x_visitor_token)
    contact = booking_svc.upsert_contact(db, conv.org_id, body.name, body.email, body.phone, body.birthday,
                                         body.marketing_consent)
    conv.contact_id = contact.id
    conv.needs_attention = True
    if body.message.strip():
        _add(db, conv, "visitor", body.message.strip())
    thanks = _add(db, conv, "assistant", f"Thanks {contact.name.split(' ')[0]}! Our team will get back to you soon. 🙌")
    if not conv.lead_notified:
        conv.lead_notified = True
        background.add_task(in_new_session, notify_lead, conv.org_id, contact.id, conv.id, body.message[:1000])
    db.commit()
    return {"messages": [_msg(thanks)]}


# --------------------------------------------------------------------------- booking
@router.get("/{key}/slots")
def slots(key: str, request: Request, service_id: str = Query(max_length=36), day: date | None = None,
          db: Session = Depends(get_db)):
    _limit(request, "slots", 60, 60)
    org, cfg = _org_by_key(db, key)
    service = db.get(Service, service_id)
    if not cfg.booking_enabled or service is None or service.org_id != org.id or not service.active:
        raise HTTPException(status_code=404, detail="Service not found")
    tz = ZoneInfo(org.timezone)
    if day is None:
        times = booking_svc.next_slots(db, org, cfg, service, limit=8)
    else:
        times = booking_svc.day_slots(db, org, cfg, service, day)
    return {"timezone": org.timezone, "slots": [
        {"start": t.isoformat(), "label": t.astimezone(tz).strftime("%a %b %-d, %-I:%M %p")} for t in times]}


@router.post("/conversations/{conversation_id}/book")
def book(conversation_id: str, body: PublicBookIn, request: Request, background: BackgroundTasks,
         x_visitor_token: str | None = Header(default=None, max_length=100), db: Session = Depends(get_db)):
    _limit(request, "book", 6, 600)
    conv = _visitor_conversation(db, conversation_id, x_visitor_token)
    org = db.get(Organization, conv.org_id)
    cfg = db.get(AssistantConfig, conv.org_id)
    if cfg.require_phone and not body.phone.strip():
        raise HTTPException(status_code=422, detail="A phone number is required.")
    if not usage.subscription_active(org):
        raise HTTPException(status_code=503, detail=_unavailable_text(cfg))
    contact = booking_svc.upsert_contact(db, org.id, body.name, body.email, body.phone, body.birthday,
                                         body.marketing_consent)
    try:
        appt, _ = booking_svc.book(db, org, body.service_id, body.start, contact, body.notes, conv.id)
    except booking_svc.BookingError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    conv.contact_id = contact.id
    service = db.get(Service, appt.service_id)
    when = appt.start.astimezone(ZoneInfo(org.timezone)).strftime("%A, %B %-d at %-I:%M %p")
    msg = _add(db, conv, "assistant", f"You're booked! ✅ {service.name} on {when}. "
                                      f"A confirmation has been sent to {contact.email}.")
    db.commit()
    background.add_task(in_new_session, notify_booking, org.id, appt.id)
    return {"appointment": {"id": appt.id, "start": appt.start.isoformat(), "service": service.name, "when": when},
            "messages": [_msg(msg)]}


# --------------------------------------------------------------------------- unsubscribe (email link)
@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(c: str = Query(max_length=36), s: str = Query(max_length=64), db: Session = Depends(get_db)):
    contact = db.get(Contact, c)
    ok = contact is not None and constant_time_equals(unsubscribe_sig(c), s)
    if ok:
        contact.marketing_consent = False
        contact.unsubscribed_at = utcnow()
        db.commit()
    text = "You've been unsubscribed and won't receive these emails again." if ok else "This unsubscribe link is invalid."
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                        f"<title>Unsubscribe</title><body style='font-family:system-ui;padding:40px;text-align:center'>"
                        f"<p>{text}</p></body>",
                        headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})

