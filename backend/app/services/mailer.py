"""Outbound email. Logs instead of sending when SMTP isn't configured (development)."""
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import get_settings

log = logging.getLogger("app.mailer")


def _clean_header(v: str) -> str:
    return re.sub(r"[\r\n]+", " ", v or "").strip()[:300]


def send_email(to: str, subject: str, body: str, from_name: str | None = None, reply_to: str | None = None,
               unsubscribe_url: str | None = None) -> bool:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = formataddr((_clean_header(from_name or s.app_name), s.smtp_from))
    msg["To"] = _clean_header(to)
    msg["Subject"] = _clean_header(subject)
    if reply_to:
        msg["Reply-To"] = _clean_header(reply_to)
    if unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{_clean_header(unsubscribe_url)}>"
        body = f"{body}\n\n—\nUnsubscribe: {unsubscribe_url}"
    msg.set_content(body)
    if not s.smtp_host:
        (log.error if s.is_production else log.warning)("MAIL (not sent, SMTP unset) to=%s subject=%s\n%s",
                                                        to, subject, body)
        return not s.is_production
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password or "")
            smtp.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log.error("SMTP send failed: %s", type(exc).__name__)
        return False


def send_system_email(to: str, subject: str, body: str) -> None:
    send_email(to, subject, body)
