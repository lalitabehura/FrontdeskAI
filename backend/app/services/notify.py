"""Transactional and automated messages: lead alerts, booking confirmations, reminders, birthday wishes."""
import calendar
import hashlib
import hmac
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import utcnow
from app.models import Appointment, AssistantConfig, Contact, MessageLog, Organization, Service
from app.services.mailer import send_email
from app.services.usage import subscription_active
from app.timefmt import long_label

log = logging.getLogger("app.notify")


def _claim(db: Session, org_id: str, kind: str, to: str, key: str, contact_id: str | None = None) -> bool:
    """Insert a dedupe row first; only the first claimant sends (safe across concurrent workers)."""
    try:
        with db.begin_nested():
            db.add(MessageLog(org_id=org_id, contact_id=contact_id, kind=kind, to=to[:320], dedupe_key=key[:120]))
        return True
    except IntegrityError:
        return False


def unsubscribe_sig(contact_id: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), f"unsub:{contact_id}".encode(), hashlib.sha256).hexdigest()[:32]


def unsubscribe_url(contact_id: str) -> str:
    return f"{get_settings().frontend_url}/api/v1/public/unsubscribe?c={contact_id}&s={unsubscribe_sig(contact_id)}"


def _local(dt: datetime, org: Organization) -> str:
    return long_label(dt.astimezone(ZoneInfo(org.timezone)))


def _dashboard(path: str) -> str:
    return f"{get_settings().frontend_url}{path}"


# --------------------------------------------------------------------------- real-time notifications
def lead_alert(db: Session, org: Organization, cfg: AssistantConfig, contact: Contact, conversation_id: str,
               message: str = "") -> None:
    if not cfg.notify_email or not _claim(db, org.id, "lead_alert", cfg.notify_email, f"lead:{conversation_id}",
                                          contact.id):
        return
    send_email(cfg.notify_email, f"New lead from your website: {contact.name or contact.email}",
               f"{contact.name} left their details via your website assistant.\n\n"
               f"Email: {contact.email or '-'}\nPhone: {contact.phone or '-'}\n"
               + (f"Message: {message}\n" if message else "")
               + f"\nOpen the conversation: {_dashboard('/inbox?c=' + conversation_id)}",
               from_name=get_settings().app_name, reply_to=contact.email or None)


def handoff_alert(db: Session, org: Organization, cfg: AssistantConfig, conversation_id: str, preview: str) -> None:
    if not cfg.notify_email or not _claim(db, org.id, "handoff_alert", cfg.notify_email, f"handoff:{conversation_id}"):
        return
    send_email(cfg.notify_email, "A website visitor asked for a person",
               f"Message: {preview[:500]}\n\nReply from your inbox: {_dashboard('/inbox?c=' + conversation_id)}")


def booking_confirmation(db: Session, org: Organization, cfg: AssistantConfig, appt: Appointment, contact: Contact,
                         service: Service) -> None:
    when = _local(appt.start, org)
    if contact.email and _claim(db, org.id, "booking_confirmation", contact.email, f"confirm:{appt.id}", contact.id):
        send_email(contact.email, f"Your booking at {org.name} is confirmed",
                   f"Hi {contact.name.split(' ')[0] if contact.name else 'there'},\n\n"
                   f"You're booked for {service.name} on {when} ({org.timezone}).\n"
                   + (f"Address: {cfg.address}\n" if cfg.address else "")
                   + "\nNeed to change or cancel? Reply to this email"
                   + (f" or call {cfg.contact_phone}" if cfg.contact_phone else "") + ".\n\n"
                   f"See you soon,\n{org.name}",
                   from_name=org.name, reply_to=cfg.contact_email or None)
    if cfg.notify_email and _claim(db, org.id, "booking_alert", cfg.notify_email, f"alert:{appt.id}", contact.id):
        send_email(cfg.notify_email, f"New booking: {service.name} — {when}",
                   f"{contact.name} ({contact.email or contact.phone}) booked {service.name} on {when}.\n"
                   + (f"Notes: {appt.notes}\n" if appt.notes else "")
                   + f"\nManage bookings: {_dashboard('/appointments')}")


# --------------------------------------------------------------------------- scheduled jobs
def _active_orgs(db: Session) -> list[tuple[Organization, AssistantConfig]]:
    rows = db.execute(select(Organization, AssistantConfig).join(
        AssistantConfig, AssistantConfig.org_id == Organization.id)).all()
    return [(o, c) for o, c in rows if subscription_active(o)]


def run_reminders(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    sent = 0
    for org, cfg in _active_orgs(db):
        if not cfg.reminders_enabled:
            continue
        horizon = now + timedelta(hours=cfg.reminder_hours_before)
        appts = db.scalars(select(Appointment).where(
            Appointment.org_id == org.id, Appointment.status.in_(("booked", "confirmed")),
            Appointment.reminder_sent_at.is_(None), Appointment.start > now, Appointment.start <= horizon)).all()
        for a in appts:
            contact = db.get(Contact, a.contact_id) if a.contact_id else None
            service = db.get(Service, a.service_id) if a.service_id else None
            a.reminder_sent_at = now
            if not contact or not contact.email:
                continue
            if _claim(db, org.id, "reminder", contact.email, f"reminder:{a.id}", contact.id):
                send_email(contact.email, f"Reminder: your appointment at {org.name}",
                           f"Hi {contact.name.split(' ')[0] if contact.name else 'there'},\n\n"
                           f"This is a friendly reminder of your {service.name if service else 'appointment'} "
                           f"on {_local(a.start, org)}.\n"
                           + (f"Address: {cfg.address}\n" if cfg.address else "")
                           + "\nCan't make it? Just reply to this email"
                           + (f" or call {cfg.contact_phone}" if cfg.contact_phone else "") + ".\n\n"
                           f"See you soon,\n{org.name}", from_name=org.name, reply_to=cfg.contact_email or None)
                sent += 1
    db.flush()
    return sent


def _is_birthday(bday: date, today: date) -> bool:
    if bday.month == 2 and bday.day == 29 and not calendar.isleap(today.year):
        return today.month == 2 and today.day == 28
    return (bday.month, bday.day) == (today.month, today.day)


def render_template(template: str, **values: str) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    return out


def run_birthdays(db: Session, now: datetime | None = None, send_hour: int = 9) -> int:
    """Send birthday wishes once per contact per year, at/after `send_hour` local time, consented contacts only."""
    now = now or utcnow()
    sent = 0
    for org, cfg in _active_orgs(db):
        if not cfg.birthday_enabled or org.plan == "starter":  # birthday wishes: Growth plan and above
            continue
        local = now.astimezone(ZoneInfo(org.timezone))
        if local.hour < send_hour:
            continue
        contacts = db.scalars(select(Contact).where(
            Contact.org_id == org.id, Contact.birthday.is_not(None), Contact.marketing_consent.is_(True),
            Contact.unsubscribed_at.is_(None), Contact.email != "")).all()
        for c in contacts:
            if not _is_birthday(c.birthday, local.date()):
                continue
            if not _claim(db, org.id, "birthday", c.email, f"birthday:{c.id}:{local.year}", c.id):
                continue
            values = {"first_name": c.name.split(" ")[0] if c.name else "there", "name": c.name or "there",
                      "business": org.name, "offer": cfg.birthday_offer or "a special treat"}
            send_email(c.email, render_template(cfg.birthday_subject, **values),
                       render_template(cfg.birthday_message, **values), from_name=org.name,
                       reply_to=cfg.contact_email or None, unsubscribe_url=unsubscribe_url(c.id))
            sent += 1
    db.flush()
    return sent
