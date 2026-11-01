"""Request/response schemas with strict input limits."""
import re
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _check_tz(v: str) -> str:
    try:
        ZoneInfo(v)
    except Exception as exc:
        raise ValueError("Unknown timezone") from exc
    return v


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DOMAIN = re.compile(r"^(\*\.)?([a-z0-9-]+\.)+[a-z]{2,}$|^localhost(:\d+)?$")
Role = Literal["owner", "admin", "staff"]


# --------------------------------------------------------------------------- auth
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(default="", max_length=120)
    business_name: str | None = Field(default=None, max_length=120)
    timezone: str = Field(default="UTC", max_length=64)
    invite_token: str | None = Field(default=None, max_length=200)
    _tz = field_validator("timezone")(_check_tz)

    @model_validator(mode="after")
    def _org_or_invite(self):
        if not self.invite_token and not (self.business_name or "").strip():
            raise ValueError("business_name is required")
        return self


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    mfa_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    recovery_code: str | None = Field(default=None, max_length=32)


class UserOut(ORM):
    id: str
    email: str
    full_name: str
    mfa_enabled: bool
    is_platform_admin: bool
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class PasswordForgotIn(BaseModel):
    email: EmailStr


class PasswordResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=12, max_length=128)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class MfaCodeIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class MfaDisableIn(BaseModel):
    password: str = Field(max_length=128)
    code: str = Field(pattern=r"^\d{6}$")


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]


class SessionOut(BaseModel):
    id: str
    created_at: datetime
    user_agent: str
    ip: str
    current: bool


class ProfileIn(BaseModel):
    full_name: str = Field(max_length=120)


# --------------------------------------------------------------------------- orgs & team
class OrgOut(ORM):
    id: str
    name: str
    industry: str
    timezone: str
    plan: str
    subscription_status: str
    trial_ends_at: datetime | None
    current_period_end: datetime | None
    onboarded: bool
    created_at: datetime


class OrgWithRole(OrgOut):
    role: str


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = Field(default="UTC", max_length=64)
    _tz = field_validator("timezone")(_check_tz)


class OrgUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    industry: str | None = Field(default=None, max_length=60)
    timezone: str | None = Field(default=None, max_length=64)
    onboarded: bool | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        return _check_tz(v) if v else v


class MemberOut(BaseModel):
    id: str
    user_id: str
    email: str
    full_name: str
    role: str
    created_at: datetime


class InviteIn(BaseModel):
    email: EmailStr
    role: Literal["admin", "staff"] = "staff"


class InviteOut(ORM):
    id: str
    email: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime


class InviteCreated(InviteOut):
    invite_url: str


class RoleIn(BaseModel):
    role: Role


class AcceptInviteIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


# --------------------------------------------------------------------------- assistant config
def validate_hours(v: dict) -> dict:
    """{"0": [["09:00","17:00"]], ... "6": []}  (0 = Monday)"""
    out: dict[str, list[list[str]]] = {}
    for day in map(str, range(7)):
        ranges = v.get(day, []) or []
        if len(ranges) > 4:
            raise ValueError("At most 4 opening ranges per day")
        clean = []
        for r in ranges:
            if len(r) != 2 or not all(_HHMM.match(x) for x in r) or r[0] >= r[1]:
                raise ValueError(f"Invalid hours for day {day}: {r}")
            clean.append([r[0], r[1]])
        clean.sort()
        for a, b in zip(clean, clean[1:], strict=False):
            if b[0] < a[1]:
                raise ValueError(f"Overlapping hours on day {day}")
        out[day] = clean
    return out


class AssistantIn(BaseModel):
    enabled: bool = True
    assistant_name: str = Field(min_length=1, max_length=60)
    greeting: str = Field(min_length=1, max_length=500)
    tone: Literal["friendly", "professional", "playful", "concise"] = "friendly"
    language: str = Field(default="auto", max_length=40)
    brand_color: str = Field(default="#1f3a5f", pattern=r"^#[0-9a-fA-F]{6}$")
    position: Literal["right", "left"] = "right"
    business_description: str = Field(default="", max_length=4000)
    extra_instructions: str = Field(default="", max_length=2000)
    contact_email: EmailStr | Literal[""] = ""
    contact_phone: str = Field(default="", max_length=40)
    address: str = Field(default="", max_length=300)
    website: str = Field(default="", max_length=300)
    hours: dict[str, list[list[str]]]
    booking_enabled: bool = True
    slot_interval_minutes: int = Field(default=30, ge=5, le=240)
    min_notice_minutes: int = Field(default=120, ge=0, le=10080)
    booking_horizon_days: int = Field(default=30, ge=1, le=180)
    capacity_per_slot: int = Field(default=1, ge=1, le=50)
    require_phone: bool = False
    allowed_domains: list[str] = Field(default_factory=list, max_length=20)
    notify_email: EmailStr | Literal[""] = ""
    handoff_message: str = Field(default="", max_length=500)
    reminders_enabled: bool = True
    reminder_hours_before: int = Field(default=24, ge=1, le=168)
    birthday_enabled: bool = False
    birthday_subject: str = Field(default="", max_length=200)
    birthday_message: str = Field(default="", max_length=3000)
    birthday_offer: str = Field(default="", max_length=200)

    _hours = field_validator("hours")(validate_hours)

    @field_validator("allowed_domains")
    @classmethod
    def _domains(cls, v: list[str]) -> list[str]:
        out = []
        for d in v:
            d = re.sub(r"^https?://", "", d.strip().lower()).rstrip("/")
            if not d:
                continue
            if not _DOMAIN.match(d):
                raise ValueError(f"Invalid domain: {d}")
            out.append(d)
        return sorted(set(out))

    @field_validator("birthday_subject")
    @classmethod
    def _one_line(cls, v: str) -> str:
        if re.search(r"[\r\n]", v):
            raise ValueError("Subject must be one line")
        return v


class AssistantOut(AssistantIn, ORM):
    widget_key: str
    updated_at: datetime


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    duration_minutes: int = Field(default=30, ge=5, le=600)
    price_text: str = Field(default="", max_length=60)
    bookable: bool = True
    active: bool = True
    sort_order: int = Field(default=0, ge=0, le=1000)


class ServiceOut(ServiceIn, ORM):
    id: str


class KnowledgeIn(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    answer: str = Field(min_length=1, max_length=4000)


class KnowledgeOut(KnowledgeIn, ORM):
    id: str
    created_at: datetime


class TestChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list, max_length=20)


# --------------------------------------------------------------------------- contacts / conversations / appointments
class ContactIn(BaseModel):
    name: str = Field(default="", max_length=120)
    email: EmailStr | Literal[""] = ""
    phone: str = Field(default="", max_length=40, pattern=r"^[0-9+()\-.\s]*$")
    birthday: date | None = None
    notes: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    marketing_consent: bool = False

    @model_validator(mode="after")
    def _identifiable(self):
        if not (self.name.strip() or self.email or self.phone.strip()):
            raise ValueError("Provide a name, email or phone")
        return self


class ContactOut(ORM):
    id: str
    name: str
    email: str
    phone: str
    birthday: date | None
    notes: str
    tags: list[str]
    source: str
    marketing_consent: bool
    unsubscribed_at: datetime | None
    created_at: datetime
    last_seen_at: datetime


class ConversationOut(ORM):
    id: str
    contact_id: str | None
    status: str
    needs_attention: bool
    channel: str
    page_url: str
    message_count: int
    created_at: datetime
    last_message_at: datetime


class ConversationListItem(ConversationOut):
    contact_name: str = ""
    contact_email: str = ""
    preview: str = ""


class MessageOut(ORM):
    id: int
    role: str
    content: str
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]
    contact: ContactOut | None


class StaffReplyIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ConversationUpdate(BaseModel):
    status: Literal["ai", "human", "closed"] | None = None
    needs_attention: bool | None = None


AppointmentStatus = Literal["booked", "confirmed", "cancelled", "completed", "no_show"]


class AppointmentOut(ORM):
    id: str
    contact_id: str | None
    service_id: str | None
    conversation_id: str | None
    start: datetime
    end: datetime
    status: str
    notes: str
    created_via: str
    reminder_sent_at: datetime | None
    created_at: datetime


class AppointmentDetail(AppointmentOut):
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    service_name: str = ""


class AppointmentCreate(BaseModel):
    service_id: str = Field(max_length=36)
    start: datetime
    contact_id: str | None = Field(default=None, max_length=36)
    name: str = Field(default="", max_length=120)
    email: EmailStr | Literal[""] = ""
    phone: str = Field(default="", max_length=40, pattern=r"^[0-9+()\-.\s]*$")
    notes: str = Field(default="", max_length=2000)
    skip_availability_check: bool = False


class AppointmentUpdate(BaseModel):
    status: AppointmentStatus | None = None
    notes: str | None = Field(default=None, max_length=2000)


# --------------------------------------------------------------------------- public widget
class PublicStartIn(BaseModel):
    page_url: str = Field(default="", max_length=500)


class PublicMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class PublicContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr | Literal[""] = ""
    phone: str = Field(default="", max_length=40, pattern=r"^[0-9+()\-.\s]*$")
    message: str = Field(default="", max_length=2000)
    birthday: date | None = None
    marketing_consent: bool = False

    @model_validator(mode="after")
    def _reachable(self):
        if not self.email and not self.phone.strip():
            raise ValueError("Provide an email or phone number")
        return self


class PublicBookIn(BaseModel):
    service_id: str = Field(max_length=36)
    start: datetime
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(default="", max_length=40, pattern=r"^[0-9+()\-.\s]*$")
    notes: str = Field(default="", max_length=1000)
    birthday: date | None = None
    marketing_consent: bool = False

    @field_validator("start")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("start must include a timezone offset")
        return v


# --------------------------------------------------------------------------- billing
class CheckoutIn(BaseModel):
    plan: Literal["starter", "growth", "pro"]
