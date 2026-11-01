"""Team inbox (conversations) and contacts (the business's customers)."""
import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.db import get_db
from app.deps import OrgContext, get_org_context, require_role
from app.models import Appointment, Contact, Conversation, ConversationMessage
from app.schemas import (
    ContactIn,
    ContactOut,
    ConversationDetail,
    ConversationListItem,
    ConversationOut,
    ConversationUpdate,
    MessageOut,
    StaffReplyIn,
)
from app.services import audit
from app.services.booking import upsert_contact

router = APIRouter(tags=["inbox"])


def _like(q: str) -> str:
    return "%" + q.replace("\\", "").replace("%", "").replace("_", "") + "%"


# --------------------------------------------------------------------------- conversations
def _conv(db: Session, ctx: OrgContext, conv_id: str) -> Conversation:
    c = db.get(Conversation, conv_id)
    if c is None or c.org_id != ctx.org_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return c


@router.get("/conversations", response_model=list[ConversationListItem])
def list_conversations(status: str | None = Query(default=None, pattern="^(ai|human|closed|attention|leads)$"),
                       limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
                       ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    stmt = select(Conversation).where(Conversation.org_id == ctx.org_id, Conversation.channel == "web",
                                      Conversation.message_count > 1)
    if status == "attention":
        stmt = stmt.where(Conversation.needs_attention.is_(True))
    elif status == "leads":
        stmt = stmt.where(Conversation.contact_id.is_not(None))
    elif status:
        stmt = stmt.where(Conversation.status == status)
    convs = db.scalars(stmt.order_by(Conversation.last_message_at.desc()).offset(offset).limit(limit)).all()
    contacts = {c.id: c for c in db.scalars(select(Contact).where(
        Contact.id.in_([c.contact_id for c in convs if c.contact_id]))).all()} if convs else {}
    out = []
    for c in convs:
        last = db.scalar(select(ConversationMessage).where(ConversationMessage.conversation_id == c.id,
                                                           ConversationMessage.role == "visitor")
                         .order_by(ConversationMessage.id.desc()).limit(1))
        contact = contacts.get(c.contact_id)
        out.append(ConversationListItem(**ConversationOut.model_validate(c).model_dump(),
                                        contact_name=contact.name if contact else "",
                                        contact_email=contact.email if contact else "",
                                        preview=(last.content[:140] if last else "")))
    return out


@router.get("/conversations/{conv_id}", response_model=ConversationDetail)
def get_conversation(conv_id: str, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    c = _conv(db, ctx, conv_id)
    msgs = db.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == c.id)
                      .order_by(ConversationMessage.id)).all()
    contact = db.get(Contact, c.contact_id) if c.contact_id else None
    return ConversationDetail(**ConversationOut.model_validate(c).model_dump(),
                              messages=[MessageOut.model_validate(m) for m in msgs],
                              contact=ContactOut.model_validate(contact) if contact else None)


@router.post("/conversations/{conv_id}/reply", response_model=MessageOut)
def reply(conv_id: str, body: StaffReplyIn, request: Request, ctx: OrgContext = Depends(get_org_context),
          db: Session = Depends(get_db)):
    """Staff reply. Automatically switches the conversation to human mode so the AI stops answering."""
    c = _conv(db, ctx, conv_id)
    m = ConversationMessage(org_id=ctx.org_id, conversation_id=c.id, role="staff", content=body.content.strip(),
                            author_id=ctx.user.id)
    db.add(m)
    c.status, c.needs_attention = "human", False
    c.message_count += 1
    c.last_message_at = utcnow()
    audit.record(db, "conversation.replied", ctx.user.id, request, org_id=ctx.org_id, conversation=c.id)
    db.commit()
    return m


@router.patch("/conversations/{conv_id}", response_model=ConversationOut)
def update_conversation(conv_id: str, body: ConversationUpdate, ctx: OrgContext = Depends(get_org_context),
                        db: Session = Depends(get_db)):
    c = _conv(db, ctx, conv_id)
    if body.status is not None:
        c.status = body.status
        if body.status == "closed":
            c.needs_attention = False
    if body.needs_attention is not None:
        c.needs_attention = body.needs_attention
    db.commit()
    return c


@router.delete("/conversations/{conv_id}", status_code=204)
def delete_conversation(conv_id: str, request: Request, ctx: OrgContext = Depends(require_role("admin")),
                        db: Session = Depends(get_db)):
    c = _conv(db, ctx, conv_id)
    db.query(ConversationMessage).filter(ConversationMessage.conversation_id == c.id).delete()
    db.delete(c)
    audit.record(db, "conversation.deleted", ctx.user.id, request, org_id=ctx.org_id)
    db.commit()


# --------------------------------------------------------------------------- contacts
def _contact(db: Session, ctx: OrgContext, contact_id: str) -> Contact:
    c = db.get(Contact, contact_id)
    if c is None or c.org_id != ctx.org_id:
        raise HTTPException(status_code=404, detail="Contact not found")
    return c


@router.get("/contacts", response_model=list[ContactOut])
def list_contacts(q: str | None = Query(default=None, max_length=100), limit: int = Query(default=100, ge=1, le=500),
                  offset: int = Query(default=0, ge=0), ctx: OrgContext = Depends(get_org_context),
                  db: Session = Depends(get_db)):
    stmt = select(Contact).where(Contact.org_id == ctx.org_id)
    if q:
        stmt = stmt.where(or_(Contact.name.ilike(_like(q)), Contact.email.ilike(_like(q)), Contact.phone.ilike(_like(q))))
    return db.scalars(stmt.order_by(Contact.last_seen_at.desc()).offset(offset).limit(limit)).all()


@router.post("/contacts", response_model=ContactOut, status_code=201)
def create_contact(body: ContactIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    c = upsert_contact(db, ctx.org_id, body.name, body.email, body.phone, body.birthday, body.marketing_consent,
                       source="manual")
    c.notes, c.tags = body.notes, [t.strip()[:32] for t in body.tags if t.strip()]
    db.commit()
    return c


@router.put("/contacts/{contact_id}", response_model=ContactOut)
def update_contact(contact_id: str, body: ContactIn, ctx: OrgContext = Depends(get_org_context),
                   db: Session = Depends(get_db)):
    c = _contact(db, ctx, contact_id)
    c.name, c.email, c.phone = body.name.strip(), (body.email or "").lower(), body.phone.strip()
    c.birthday, c.notes = body.birthday, body.notes
    c.tags = [t.strip()[:32] for t in body.tags if t.strip()]
    if body.marketing_consent and not c.marketing_consent:
        c.marketing_consent, c.unsubscribed_at = True, None
    elif not body.marketing_consent:
        c.marketing_consent = False
    db.commit()
    return c


@router.delete("/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: str, request: Request, ctx: OrgContext = Depends(require_role("admin")),
                   db: Session = Depends(get_db)):
    """Erase a customer (privacy request): contact + their conversations; appointments are anonymised."""
    c = _contact(db, ctx, contact_id)
    for conv in db.scalars(select(Conversation).where(Conversation.contact_id == c.id)).all():
        db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conv.id).delete()
        db.delete(conv)
    db.query(Appointment).filter(Appointment.contact_id == c.id).update({"contact_id": None, "notes": ""})
    db.delete(c)
    audit.record(db, "contact.erased", ctx.user.id, request, org_id=ctx.org_id)
    db.commit()


def _csv_safe(v: str) -> str:
    """Prevent CSV/formula injection when the file is opened in Excel/Sheets."""
    v = v or ""
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


@router.get("/contacts/export.csv")
def export_contacts(request: Request, ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "email", "phone", "birthday", "marketing_consent", "source", "tags", "notes", "created_at"])
    for c in db.scalars(select(Contact).where(Contact.org_id == ctx.org_id).order_by(Contact.created_at)).all():
        w.writerow([_csv_safe(c.name), _csv_safe(c.email), _csv_safe(c.phone), c.birthday.isoformat() if c.birthday else "",
                    "yes" if c.marketing_consent and not c.unsubscribed_at else "no", c.source,
                    _csv_safe(";".join(c.tags or [])), _csv_safe(c.notes), c.created_at.isoformat()])
    audit.record(db, "contacts.exported", ctx.user.id, request, org_id=ctx.org_id)
    db.commit()
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="contacts.csv"'})


@router.post("/contacts/import")
async def import_contacts(request: Request, file: UploadFile = File(...), ctx: OrgContext = Depends(require_role("admin")),
                          db: Session = Depends(get_db)):
    """CSV with headers: name, email, phone, birthday (YYYY-MM-DD), marketing_consent (yes/no)."""
    raw = await file.read(1_000_001)
    if len(raw) > 1_000_000:
        raise HTTPException(status_code=413, detail="File too large (max 1 MB).")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 CSV.") from None
    reader = csv.DictReader(io.StringIO(text))
    existing = db.scalar(select(func.count()).select_from(Contact).where(Contact.org_id == ctx.org_id))
    added, skipped, errors = 0, 0, []
    for i, row in enumerate(reader, start=2):
        if existing + added >= 50_000:
            errors.append("Contact limit reached (50,000).")
            break
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        name, email, phone = row.get("name", "")[:120], row.get("email", "").lower()[:320], row.get("phone", "")[:40]
        if not (name or email or phone) or (email and "@" not in email):
            skipped += 1
            continue
        bday = None
        if row.get("birthday"):
            try:
                bday = date.fromisoformat(row["birthday"])
            except ValueError:
                errors.append(f"Row {i}: invalid birthday '{row['birthday'][:20]}' (use YYYY-MM-DD)")
        consent = row.get("marketing_consent", "").lower() in ("yes", "true", "1", "y")
        upsert_contact(db, ctx.org_id, name, email, phone, bday, consent, source="import")
        added += 1
        if i > 20_000:
            break
    audit.record(db, "contacts.imported", ctx.user.id, request, org_id=ctx.org_id, count=added)
    db.commit()
    return {"imported": added, "skipped": skipped, "errors": errors[:20]}
