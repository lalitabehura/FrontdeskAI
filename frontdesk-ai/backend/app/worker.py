"""Background worker (arq + Redis): reminders, birthday wishes, housekeeping.

Run: arq app.worker.WorkerSettings
"""
import asyncio
import logging
from datetime import timedelta

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import delete

from app.core.config import get_settings
from app.core.security import utcnow
from app.db import SessionLocal
from app.models import Invitation, PasswordResetToken, RefreshToken
from app.services.notify import run_birthdays, run_reminders

log = logging.getLogger("app.worker")


def _run(fn) -> int:
    with SessionLocal() as db:
        try:
            n = fn(db)
            db.commit()
            return n or 0
        except Exception:
            db.rollback()
            log.exception("job %s failed", fn.__name__)
            return 0


def _housekeeping(db) -> int:
    now = utcnow()
    db.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at < now - timedelta(days=1)))
    db.execute(delete(RefreshToken).where(RefreshToken.expires_at < now - timedelta(days=1)))
    db.execute(delete(Invitation).where(Invitation.expires_at < now - timedelta(days=30)))
    return 0


async def reminders(ctx) -> int:
    return await asyncio.to_thread(_run, run_reminders)


async def birthdays(ctx) -> int:
    return await asyncio.to_thread(_run, run_birthdays)


async def housekeeping(ctx) -> int:
    return await asyncio.to_thread(_run, _housekeeping)


class WorkerSettings:
    functions = [reminders, birthdays, housekeeping]
    cron_jobs = [
        cron(reminders, minute={0, 15, 30, 45}),   # every 15 minutes
        cron(birthdays, minute={5}),                # hourly; sends once each org's local time passes 9:00
        cron(housekeeping, hour={3}, minute={20}),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379/0")
    max_jobs = 4
    job_timeout = 600
