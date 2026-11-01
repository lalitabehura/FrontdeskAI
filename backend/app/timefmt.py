"""Portable date formatting. Windows' strftime has no "%-d"/"%-I" (no-padding) directives."""
from datetime import datetime


def _hour12(dt: datetime) -> str:
    return f"{(dt.hour % 12) or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def short_label(dt: datetime) -> str:
    """e.g. 'Mon Nov 3, 9:30 AM' (dt already in local time)."""
    return f"{dt.strftime('%a %b')} {dt.day}, {_hour12(dt)}"


def long_label(dt: datetime) -> str:
    """e.g. 'Monday, November 3 at 9:30 AM' (dt already in local time)."""
    return f"{dt.strftime('%A, %B')} {dt.day} at {_hour12(dt)}"
