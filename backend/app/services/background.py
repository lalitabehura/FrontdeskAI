"""Run notification work after the response is sent, in its own DB session."""
import logging
from collections.abc import Callable

from app.db import SessionLocal

log = logging.getLogger("app.background")


def in_new_session(fn: Callable, *args) -> None:
    with SessionLocal() as db:
        try:
            fn(db, *args)
            db.commit()
        except Exception:
            db.rollback()
            log.exception("background task %s failed", getattr(fn, "__name__", fn))


def notify_lead(db, org_id: str, contact_id: str, conversation_id: str, message: str = "") -> None:
    from app.models import AssistantConfig, Contact, Organization
    from app.services.notify import lead_alert

    lead_alert(db, db.get(Organization, org_id), db.get(AssistantConfig, org_id), db.get(Contact, contact_id),
               conversation_id, message)


def notify_handoff(db, org_id: str, conversation_id: str, preview: str) -> None:
    from app.models import AssistantConfig, Organization
    from app.services.notify import handoff_alert

    handoff_alert(db, db.get(Organization, org_id), db.get(AssistantConfig, org_id), conversation_id, preview)


def notify_booking(db, org_id: str, appointment_id: str) -> None:
    from app.models import Appointment, AssistantConfig, Contact, Organization, Service
    from app.services.notify import booking_confirmation

    appt = db.get(Appointment, appointment_id)
    booking_confirmation(db, db.get(Organization, org_id), db.get(AssistantConfig, org_id), appt,
                         db.get(Contact, appt.contact_id), db.get(Service, appt.service_id))
