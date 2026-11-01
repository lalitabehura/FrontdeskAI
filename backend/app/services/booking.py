"""Availability and booking. All times stored UTC; opening hours interpreted in the org's timezone."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_token, new_opaque_token, utcnow
from app.models import Appointment, AssistantConfig, Contact, Organization, Service

BLOCKING = ("booked", "confirmed")
UTC = ZoneInfo("UTC")


class BookingError(ValueError):
    pass


def _hm(v: str) -> time:
    h, m = v.split(":")
    return time(int(h), int(m))


def day_slots(db: Session, org: Organization, cfg: AssistantConfig, service: Service, day: date) -> list[datetime]:
    """Bookable start times (UTC) for `service` on local `day`."""
    tz = ZoneInfo(org.timezone)
    now = utcnow()
    earliest = now + timedelta(minutes=cfg.min_notice_minutes)
    latest_day = now.astimezone(tz).date() + timedelta(days=cfg.booking_horizon_days)
    if day > latest_day or day < now.astimezone(tz).date():
        return []
    ranges = (cfg.hours or {}).get(str(day.weekday()), [])
    if not ranges:
        return []
    duration = timedelta(minutes=service.duration_minutes)
    step = timedelta(minutes=cfg.slot_interval_minutes)
    day_start = datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
    day_end = day_start + timedelta(days=1, hours=1)
    taken = db.execute(select(Appointment.start, Appointment.end).where(
        Appointment.org_id == org.id, Appointment.status.in_(BLOCKING),
        Appointment.end > day_start, Appointment.start < day_end)).all()
    out: list[datetime] = []
    for open_s, open_e in ranges:
        cursor = datetime.combine(day, _hm(open_s), tzinfo=tz)
        close = datetime.combine(day, _hm(open_e), tzinfo=tz)
        while cursor + duration <= close:
            s_utc, e_utc = cursor.astimezone(UTC), (cursor + duration).astimezone(UTC)
            if s_utc >= earliest:
                overlapping = sum(1 for ts, te in taken if ts < e_utc and te > s_utc)
                if overlapping < cfg.capacity_per_slot:
                    out.append(s_utc)
            cursor += step
    return out


def next_slots(db: Session, org: Organization, cfg: AssistantConfig, service: Service, limit: int = 6,
               days: int = 14) -> list[datetime]:
    tz = ZoneInfo(org.timezone)
    today = utcnow().astimezone(tz).date()
    found: list[datetime] = []
    for i in range(min(days, cfg.booking_horizon_days + 1)):
        found += day_slots(db, org, cfg, service, today + timedelta(days=i))
        if len(found) >= limit:
            break
    return found[:limit]


def upsert_contact(db: Session, org_id: str, name: str = "", email: str = "", phone: str = "",
                   birthday: date | None = None, marketing_consent: bool | None = None,
                   source: str = "widget") -> Contact:
    email = (email or "").strip().lower()
    phone = (phone or "").strip()
    contact = None
    if email:
        contact = db.scalar(select(Contact).where(Contact.org_id == org_id, func.lower(Contact.email) == email))
    if contact is None and phone:
        contact = db.scalar(select(Contact).where(Contact.org_id == org_id, Contact.phone == phone))
    if contact is None:
        contact = Contact(org_id=org_id, source=source, tags=[])
        db.add(contact)
    if name.strip():
        contact.name = name.strip()[:120]
    if email:
        contact.email = email
    if phone:
        contact.phone = phone[:40]
    if birthday:
        contact.birthday = birthday
    if marketing_consent:  # consent can be granted here; withdrawal happens via unsubscribe
        contact.marketing_consent = True
        contact.unsubscribed_at = None
    contact.last_seen_at = utcnow()
    db.flush()
    return contact


def book(db: Session, org: Organization, service_id: str, start: datetime, contact: Contact,
         notes: str = "", conversation_id: str | None = None, via: str = "widget",
         check_availability: bool = True) -> tuple[Appointment, str]:
    """Create an appointment. Returns (appointment, raw manage token). Serialised per org to prevent double booking."""
    # Lock the org's config row so concurrent bookings for the same business are serialised (PostgreSQL).
    cfg = db.scalar(select(AssistantConfig).where(AssistantConfig.org_id == org.id).with_for_update())
    service = db.get(Service, service_id)
    if service is None or service.org_id != org.id or not service.active or not service.bookable:
        raise BookingError("That service isn't available for booking.")
    if via == "widget" and not cfg.booking_enabled:
        raise BookingError("Online booking is turned off.")
    start = start.astimezone(UTC).replace(second=0, microsecond=0)
    if check_availability:
        tz = ZoneInfo(org.timezone)
        if start not in day_slots(db, org, cfg, service, start.astimezone(tz).date()):
            raise BookingError("Sorry, that time is no longer available. Please pick another slot.")
    raw = new_opaque_token()
    appt = Appointment(org_id=org.id, contact_id=contact.id, service_id=service.id, conversation_id=conversation_id,
                       start=start, end=start + timedelta(minutes=service.duration_minutes), notes=notes[:2000],
                       created_via=via, manage_token_hash=hash_token(raw))
    db.add(appt)
    db.flush()
    return appt, raw
