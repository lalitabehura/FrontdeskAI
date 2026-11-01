from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.db import get_db
from app.deps import OrgContext, get_org_context
from app.models import Appointment, AssistantConfig, Contact, Conversation, KnowledgeItem, Service
from app.schemas import AppointmentCreate, AppointmentDetail, AppointmentOut, AppointmentUpdate
from app.services import audit
from app.services import booking as booking_svc
from app.services.background import in_new_session, notify_booking
from app.services.usage import usage_summary

router = APIRouter(tags=["appointments"])


def _detail(db: Session, a: Appointment) -> AppointmentDetail:
    c = db.get(Contact, a.contact_id) if a.contact_id else None
    s = db.get(Service, a.service_id) if a.service_id else None
    return AppointmentDetail(**AppointmentOut.model_validate(a).model_dump(),
                             contact_name=c.name if c else "(deleted)", contact_email=c.email if c else "",
                             contact_phone=c.phone if c else "", service_name=s.name if s else "")


@router.get("/appointments", response_model=list[AppointmentDetail])
def list_appointments(start: date | None = None, days: int = Query(default=14, ge=1, le=92),
                      status: str | None = Query(default=None, pattern="^(booked|confirmed|cancelled|completed|no_show)$"),
                      ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    tz = ZoneInfo(ctx.org.timezone)
    first = datetime.combine(start or datetime.now(tz).date(), time.min, tzinfo=tz)
    stmt = select(Appointment).where(Appointment.org_id == ctx.org_id, Appointment.start >= first,
                                     Appointment.start < first + timedelta(days=days))
    if status:
        stmt = stmt.where(Appointment.status == status)
    return [_detail(db, a) for a in db.scalars(stmt.order_by(Appointment.start).limit(1000)).all()]


@router.get("/appointments/slots")
def slots(service_id: str = Query(max_length=36), day: date = Query(), ctx: OrgContext = Depends(get_org_context),
          db: Session = Depends(get_db)):
    s = db.get(Service, service_id)
    if s is None or s.org_id != ctx.org_id:
        raise HTTPException(status_code=404, detail="Service not found")
    times = booking_svc.day_slots(db, ctx.org, db.get(AssistantConfig, ctx.org_id), s, day)
    return [t.isoformat() for t in times]


@router.post("/appointments", response_model=AppointmentDetail, status_code=201)
def create(body: AppointmentCreate, request: Request, background: BackgroundTasks,
           ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    if body.contact_id:
        contact = db.get(Contact, body.contact_id)
        if contact is None or contact.org_id != ctx.org_id:
            raise HTTPException(status_code=404, detail="Contact not found")
    elif body.name or body.email or body.phone:
        contact = booking_svc.upsert_contact(db, ctx.org_id, body.name, body.email, body.phone, source="manual")
    else:
        raise HTTPException(status_code=422, detail="Choose a contact or enter their details.")
    start = body.start if body.start.tzinfo else body.start.replace(tzinfo=ZoneInfo(ctx.org.timezone))
    try:
        appt, _ = booking_svc.book(db, ctx.org, body.service_id, start, contact, body.notes, via="staff",
                                   check_availability=not body.skip_availability_check)
    except booking_svc.BookingError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    audit.record(db, "appointment.created", ctx.user.id, request, org_id=ctx.org_id)
    db.commit()
    background.add_task(in_new_session, notify_booking, ctx.org_id, appt.id)
    return _detail(db, appt)


@router.patch("/appointments/{appt_id}", response_model=AppointmentDetail)
def update(appt_id: str, body: AppointmentUpdate, request: Request, ctx: OrgContext = Depends(get_org_context),
           db: Session = Depends(get_db)):
    a = db.get(Appointment, appt_id)
    if a is None or a.org_id != ctx.org_id:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if body.status:
        a.status = body.status
    if body.notes is not None:
        a.notes = body.notes
    audit.record(db, "appointment.updated", ctx.user.id, request, org_id=ctx.org_id, status=a.status)
    db.commit()
    return _detail(db, a)


@router.get("/dashboard")
def dashboard(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    now = utcnow()
    week = now - timedelta(days=7)
    org_id = ctx.org_id

    def count(model, *where):
        return db.scalar(select(func.count()).select_from(model).where(model.org_id == org_id, *where)) or 0

    upcoming = db.scalars(select(Appointment).where(
        Appointment.org_id == org_id, Appointment.start >= now, Appointment.status.in_(("booked", "confirmed")))
        .order_by(Appointment.start).limit(5)).all()
    return {
        "conversations_7d": count(Conversation, Conversation.created_at >= week, Conversation.message_count > 1,
                                  Conversation.channel == "web"),
        "leads_7d": count(Contact, Contact.created_at >= week),
        "bookings_7d": count(Appointment, Appointment.created_at >= week),
        "needs_attention": count(Conversation, Conversation.needs_attention.is_(True)),
        "upcoming": [_detail(db, a) for a in upcoming],
        "usage": usage_summary(db, ctx.org),
        "knowledge_items": count(KnowledgeItem),
        "onboarded": ctx.org.onboarded,
    }
