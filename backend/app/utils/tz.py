"""
Timezone helpers for the Pivot App.

The user wants every date/time shown in the app to be in IST
(Indian Standard Time, UTC+5:30). The application stores all
datetimes in UTC (the SQLAlchemy column default uses
``datetime.utcnow``) for portability, and converts to the user's
configured timezone at the display boundary — never at the storage
boundary.

Where this is used
------------------
* ``now_ist()`` — current time in IST (the default; the configured
  timezone is honoured when one is set on the singleton
  ``app_settings`` row).
* ``to_ist(dt)`` — convert an aware/naive UTC ``datetime`` to the
  configured timezone.
* ``format_ist(dt, fmt=...)`` — render a ``datetime`` in IST with a
  default human-readable format.
* ``iso_ist(dt)`` — ISO-8601 string in IST (with the IST offset
  suffix so the frontend can parse it correctly).

The configured timezone is read from the singleton ``app_settings``
row at call time. If the row is missing or has no ``timezone`` set,
the default ``"Asia/Kolkata"`` is used (the user explicitly asked
for IST everywhere — even the default is IST, not UTC).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

# IANA name for Indian Standard Time.  UTC+5:30, no DST.
IST_TZ = timezone(timedelta(hours=5, minutes=30), name="IST")

# Default if the app_settings row has no timezone set.
DEFAULT_TZ_NAME = "Asia/Kolkata"

# We don't import zoneinfo (3.9+) on purpose — ``zoneinfo`` is
# available on Python 3.9+ but the project runs on Python 3.11
# inside Docker and 3.9 on the developer's machine.  ``zoneinfo``
# requires the system tzdata on Linux.  Building the fixed-offset
# ``timezone(...)`` above is portable and zero-dependency.
# For non-IST timezones we fall back to fixed-offset parsing of the
# string (e.g. "UTC", "Asia/Kolkata", "+05:30", "UTC+5:30").

_OFFSET_CACHE: dict[str, timezone] = {}


def _parse_offset(name: str) -> timezone:
    """Parse a short timezone string into a ``datetime.timezone``.

    Supports the common shapes the Settings page accepts:
      * ``UTC``                → UTC
      * ``Asia/Kolkata``       → +05:30 (the only IANA name the app
        currently exposes in the Settings UI; future additions
        can be mapped here)
      * ``+HH:MM`` / ``-HH:MM`` → fixed offset
      * ``UTC+HH:MM``          → fixed offset
    Unknown values fall back to IST so the user always sees
    a consistent local time.
    """
    if not name:
        return IST_TZ
    cached = _OFFSET_CACHE.get(name)
    if cached is not None:
        return cached
    s = name.strip()
    if s.upper() in ("UTC", "GMT", "Z"):
        tz = timezone.utc
    elif s == "Asia/Kolkata" or s.upper() == "IST":
        tz = IST_TZ
    else:
        # Try fixed-offset parsing: "+05:30", "-04:00", "UTC+5:30", "UTC-04:00".
        s2 = s.upper().replace("UTC", "").strip()
        try:
            sign = 1
            if s2.startswith("-"):
                sign = -1
                s2 = s2[1:]
            elif s2.startswith("+"):
                s2 = s2[1:]
            if ":" in s2:
                hh, mm = s2.split(":", 1)
            else:
                # "UTC+5" or "+0530"
                if len(s2) >= 4 and s2[-2:].isdigit():
                    hh, mm = s2[:-2], s2[-2:]
                else:
                    hh, mm = s2, "0"
            tz = timezone(timedelta(hours=sign * int(hh), minutes=sign * int(mm)))
        except Exception:
            tz = IST_TZ
    _OFFSET_CACHE[name] = tz
    return tz


def _db_timezone_name() -> str:
    """Read the configured timezone from the singleton app_settings
    row.  We do a direct import inside the function so this module
    has no circular-import surprises (app_settings_service imports
    from repositories which can import other things).
    """
    try:
        from app.services.app_settings_service import get_settings  # type: ignore
        from app.config.database import SessionLocal  # type: ignore
        db = SessionLocal()
        try:
            row = get_settings(db)
            return (row.timezone or DEFAULT_TZ_NAME)
        finally:
            db.close()
    except Exception:
        return DEFAULT_TZ_NAME


def _to_aware_utc(dt: datetime) -> datetime:
    """Coerce a naive ``datetime`` to an aware UTC ``datetime``.

    The SQLAlchemy models store naive UTC datetimes (the default
    callable is ``datetime.utcnow``).  When we read them back, we
    need to attach the UTC tzinfo before converting to the user's
    timezone.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_ist(dt: Optional[datetime], tz_name: Optional[str] = None) -> Optional[datetime]:
    """Convert a (naive UTC or aware) ``datetime`` to the configured
    timezone.  Returns ``None`` for a ``None`` input.
    """
    if dt is None:
        return None
    name = tz_name or _db_timezone_name()
    target_tz = _parse_offset(name)
    return _to_aware_utc(dt).astimezone(target_tz)


def now_ist(tz_name: Optional[str] = None) -> datetime:
    """Current time in the configured timezone (default IST)."""
    name = tz_name or _db_timezone_name()
    return datetime.now(tz=_parse_offset(name))


def format_ist(dt: Optional[datetime], fmt: str = "%d %b %Y, %H:%M:%S %Z", tz_name: Optional[str] = None) -> str:
    """Format a ``datetime`` in the configured timezone as a
    human-readable string.  Returns ``""`` for a ``None`` input.
    """
    if dt is None:
        return ""
    converted = to_ist(dt, tz_name=tz_name)
    if converted is None:
        return ""
    return converted.strftime(fmt)


def iso_ist(dt: Optional[datetime], tz_name: Optional[str] = None) -> str:
    """Return the ISO-8601 string of ``dt`` in the configured
    timezone (with the timezone offset suffix so the frontend
    can parse it correctly).  Returns ``""`` for ``None``.
    """
    if dt is None:
        return ""
    converted = to_ist(dt, tz_name=tz_name)
    if converted is None:
        return ""
    return converted.isoformat()
