"""Database models. Every tenant-owned row carries org_id and every query filters by it."""
import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import utcnow
from app.db import Base
from app.db_types import EncryptedText, UTCDateTime


def _uuid() -> str:
    return str(uuid.uuid4())


def _org_fk() -> Mapped[str]:
    return mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)


def _user_fk() -> Mapped[str]:
    return mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)


DEFAULT_HOURS = {str(d): [["09:00", "17:00"]] for d in range(5)} | {"5": [], "6": []}  # Mon=0


# =========================================================================== users & auth
class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    mfa_last_counter: Mapped[int] = mapped_column(Integer, default=0)
    recovery_code_hashes: Mapped[list] = mapped_column(JSON, default=list)
    password_changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = _user_fk()
    family_id: Mapped[str] = mapped_column(String(36), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    replaced_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = _user_fk()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


# =========================================================================== tenants
class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    industry: Mapped[str] = mapped_column(String(60), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    plan: Mapped[str] = mapped_column(String(20), default="growth")
    subscription_status: Mapped[str] = mapped_column(String(20), default="trialing")
    trial_ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_membership"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = _org_fk()
    user_id: Mapped[str] = _user_fk()
    role: Mapped[str] = mapped_column(String(16), default="staff")  # owner | admin | staff
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = _org_fk()
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16), default="staff")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AssistantConfig(Base):
    """Everything a business customises about its assistant."""

    __tablename__ = "assistant_configs"
    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    widget_key: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    assistant_name: Mapped[str] = mapped_column(String(60), default="Assistant")
    greeting: Mapped[str] = mapped_column(String(500), default="Hi! 👋 How can I help you today?")
    tone: Mapped[str] = mapped_column(String(20), default="friendly")  # friendly|professional|playful|concise
    language: Mapped[str] = mapped_column(String(40), default="auto")
    brand_color: Mapped[str] = mapped_column(String(7), default="#1f3a5f")
    position: Mapped[str] = mapped_column(String(8), default="right")
    business_description: Mapped[str] = mapped_column(Text, default="")
    extra_instructions: Mapped[str] = mapped_column(Text, default="")
    contact_email: Mapped[str] = mapped_column(String(320), default="")
    contact_phone: Mapped[str] = mapped_column(String(40), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    website: Mapped[str] = mapped_column(String(300), default="")
    hours: Mapped[dict] = mapped_column(JSON, default=lambda: dict(DEFAULT_HOURS))
    booking_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    slot_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    min_notice_minutes: Mapped[int] = mapped_column(Integer, default=120)
    booking_horizon_days: Mapped[int] = mapped_column(Integer, default=30)
    capacity_per_slot: Mapped[int] = mapped_column(Integer, default=1)
    require_phone: Mapped[bool] = mapped_column(Boolean, default=False)
    allowed_domains: Mapped[list] = mapped_column(JSON, default=list)  # empty = any site
    notify_email: Mapped[str] = mapped_column(String(320), default="")
    handoff_message: Mapped[str] = mapped_column(
        String(500), default="I'll pass this to our team — leave your contact details and we'll get back to you shortly.")
    # automations
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_hours_before: Mapped[int] = mapped_column(Integer, default=24)
    birthday_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    birthday_subject: Mapped[str] = mapped_column(String(200), default="Happy birthday from {business}! 🎉")
    birthday_message: Mapped[str] = mapped_column(
        Text, default="Hi {first_name},\n\nEveryone at {business} wishes you a wonderful birthday! "
                      "As a small gift, enjoy {offer} on your next visit this month.\n\nSee you soon!")
    birthday_offer: Mapped[str] = mapped_column(String(200), default="15% off")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Service(Base):
    __tablename__ = "services"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = _org_fk()
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(1000), default="")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    price_text: Mapped[str] = mapped_column(String(60), default="")
    bookable: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = _org_fk()
    question: Mapped[str] = mapped_column(String(300))
    answer: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# =========================================================================== customers of the business
class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (Index("ix_contact_org_email", "org_id", "email"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = _org_fk()
    name: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    birthday: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(20), default="widget")  # widget|manual|import
    marketing_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conv_org_last", "org_id", "last_message_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = _org_fk()
    contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    visitor_token_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(12), default="ai")  # ai | human | closed
    needs_attention: Mapped[bool] = mapped_column(Boolean, default=False)
    channel: Mapped[str] = mapped_column(String(12), default="web")  # web | test
    page_url: Mapped[str] = mapped_column(String(500), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    lead_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_message_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (Index("ix_msg_conv_created", "conversation_id", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = _org_fk()
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(12))  # visitor | assistant | staff | system
    content: Mapped[str] = mapped_column(EncryptedText)
    author_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (Index("ix_appt_org_start", "org_id", "start"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = _org_fk()
    contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    service_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    start: Mapped[datetime] = mapped_column(UTCDateTime)
    end: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(12), default="booked")  # booked|confirmed|cancelled|completed|no_show
    notes: Mapped[str] = mapped_column(Text, default="")
    created_via: Mapped[str] = mapped_column(String(12), default="widget")
    manage_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class MessageLog(Base):
    """Outbound automated messages (dedupe + history)."""

    __tablename__ = "message_logs"
    __table_args__ = (UniqueConstraint("org_id", "dedupe_key", name="uq_message_dedupe"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = _org_fk()
    contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(24))  # reminder|birthday|booking_confirmation|lead_alert
    channel: Mapped[str] = mapped_column(String(12), default="email")
    to: Mapped[str] = mapped_column(String(320))
    dedupe_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(12), default="sent")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class UsageCounter(Base):
    __tablename__ = "usage_counters"
    __table_args__ = (UniqueConstraint("org_id", "period", name="uq_usage_period"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = _org_fk()
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    conversations: Mapped[int] = mapped_column(Integer, default=0)
    ai_replies: Mapped[int] = mapped_column(Integer, default=0)


class StripeEvent(Base):
    __tablename__ = "stripe_events"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    type: Mapped[str] = mapped_column(String(80))
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_org_created", "org_id", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


ORG_OWNED_MODELS = [
    ConversationMessage, Conversation, Appointment, Contact, KnowledgeItem, Service, MessageLog,
    UsageCounter, Invitation, Membership, AssistantConfig,
]
