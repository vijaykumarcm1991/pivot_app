"""
Scheduled reports (#2).

A schedule runs a saved pivot and emails every data row of the result
(with the matching records attached), like selecting all rows in the
Pivot Builder and clicking Email. Use the saved pivot's Top N / threshold
value filters to control which rows are sent.

Timing
------
`run_time` ("HH:MM") is in the application timezone (Settings page).
`next_run_at` is stored as naive UTC. A background thread (started on app
startup, one per process) checks every POLL_SECONDS for due schedules. A
schedule is *claimed* with a conditional UPDATE on `next_run_at`, so even
with several processes each occurrence runs once.

If the app was down when a run was due, it runs once on startup if it is
less than MISSED_GRACE old; older missed runs are skipped and the next
occurrence is scheduled.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.models.report_schedule import ReportSchedule
from app.models.saved_pivot import SavedPivot
from app.repositories.dataset_repository import get_dataset_by_id
from app.schemas.email import EmailSendRequest
from app.services import saved_pivot_service
from app.services.app_logging import log_event
from app.utils.tz import _db_timezone_name, _parse_offset, iso_ist

logger = logging.getLogger("pivot_app.scheduler")

FREQUENCIES = ("daily", "weekdays", "weekly", "monthly")
POLL_SECONDS = 30
MISSED_GRACE = timedelta(hours=12)


class ScheduleError(ValueError):
    """Invalid schedule (HTTP 400)."""


# ── Next-run calculation ────────────────────────────────────────────────

def _parse_time(value: str) -> dtime:
    try:
        hh, mm = (value or "").strip().split(":")
        return dtime(int(hh), int(mm))
    except Exception as exc:
        raise ScheduleError(f"Invalid time '{value}' — use HH:MM (24-hour).") from exc


def _weekday_set(value: str) -> set:
    out = set()
    for part in (value or "").split(","):
        part = part.strip()
        if part:
            n = int(part)
            if not 0 <= n <= 6:
                raise ScheduleError("Weekdays must be 0 (Mon) … 6 (Sun).")
            out.add(n)
    return out


def _runs_on(sched: ReportSchedule, day: date) -> bool:
    if sched.frequency == "daily":
        return True
    if sched.frequency == "weekdays":
        return day.weekday() < 5
    if sched.frequency == "weekly":
        return day.weekday() in _weekday_set(sched.weekdays)
    if sched.frequency == "monthly":
        return day.day == int(sched.day_of_month or 1)
    return False


def compute_next_run(sched: ReportSchedule, after_utc: datetime, tz_name: Optional[str] = None) -> Optional[datetime]:
    """First occurrence strictly after `after_utc` (naive UTC), returned
    as naive UTC. Wall-clock time is interpreted in the app timezone, so
    daylight-saving zones keep the same local time."""
    tz = _parse_offset(tz_name or _db_timezone_name())
    at = _parse_time(sched.run_time)
    local_after = after_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    day = local_after.date()
    for _ in range(400):
        if _runs_on(sched, day):
            candidate = datetime.combine(day, at).replace(tzinfo=tz)
            if candidate > local_after:
                return candidate.astimezone(timezone.utc).replace(tzinfo=None)
        day += timedelta(days=1)
    return None


# ── Validation / serialisation ──────────────────────────────────────────

def _addresses(value: Any) -> List[str]:
    from app.services.email_service import parse_address_list, validate_addresses
    return validate_addresses(parse_address_list(value), "recipient")


def apply_fields(db: Session, sched: ReportSchedule, data: Dict[str, Any]) -> None:
    """Validate and copy API fields onto a schedule (not committed)."""
    from app.services.email_service import EmailValidationError

    name = (data.get("name") or "").strip()
    if not name:
        raise ScheduleError("Name is required.")
    saved_id = data.get("savedPivotId")
    if not saved_id or not saved_pivot_service.get_saved(db, int(saved_id)):
        raise ScheduleError("Choose a saved pivot.")
    frequency = (data.get("frequency") or "weekdays").lower()
    if frequency not in FREQUENCIES:
        raise ScheduleError(f"Frequency must be one of: {', '.join(FREQUENCIES)}.")
    run_time = data.get("runTime") or "09:00"
    _parse_time(run_time)
    weekdays = data.get("weekdays")
    if isinstance(weekdays, list):
        weekdays = ",".join(str(int(w)) for w in weekdays)
    weekdays = (weekdays or "").strip()
    if frequency == "weekly" and not _weekday_set(weekdays):
        raise ScheduleError("Pick at least one day for a weekly schedule.")
    weekdays = weekdays or "0"
    day_of_month = int(data.get("dayOfMonth") or 1)
    if not 1 <= day_of_month <= 28:
        raise ScheduleError("Day of month must be between 1 and 28.")
    try:
        to, cc, bcc = (_addresses(data.get(k)) for k in ("to", "cc", "bcc"))
    except EmailValidationError as exc:
        raise ScheduleError(str(exc)) from exc
    if not (to or cc or bcc):
        raise ScheduleError("Add at least one recipient.")
    subject = (data.get("subject") or "").strip()
    if not subject:
        raise ScheduleError("Subject is required.")

    sched.name = name
    sched.saved_pivot_id = int(saved_id)
    sched.enabled = bool(data.get("enabled", True))
    sched.frequency = frequency
    sched.run_time = run_time.strip()
    sched.weekdays = weekdays
    sched.day_of_month = day_of_month
    sched.to_json, sched.cc_json, sched.bcc_json = json.dumps(to), json.dumps(cc), json.dumps(bcc)
    sched.subject = subject
    sched.message = data.get("message") or ""
    sched.skip_if_empty = bool(data.get("skipIfEmpty", True))
    sched.updated_at = datetime.utcnow()
    sched.next_run_at = compute_next_run(sched, datetime.utcnow()) if sched.enabled else None


def serialize(db: Session, sched: ReportSchedule) -> Dict[str, Any]:
    saved = saved_pivot_service.get_saved(db, sched.saved_pivot_id)
    dataset = get_dataset_by_id(db, saved.dataset_id) if saved else None
    return {
        "id": sched.id,
        "name": sched.name,
        "savedPivotId": sched.saved_pivot_id,
        "savedPivotName": saved.name if saved else "(deleted)",
        "datasetName": dataset.filename if dataset else "",
        "enabled": bool(sched.enabled),
        "frequency": sched.frequency,
        "runTime": sched.run_time,
        "weekdays": [int(w) for w in (sched.weekdays or "").split(",") if w.strip()],
        "dayOfMonth": sched.day_of_month,
        "to": json.loads(sched.to_json or "[]"),
        "cc": json.loads(sched.cc_json or "[]"),
        "bcc": json.loads(sched.bcc_json or "[]"),
        "subject": sched.subject,
        "message": sched.message,
        "skipIfEmpty": bool(sched.skip_if_empty),
        "timezone": _db_timezone_name(),
        "nextRunAt": sched.next_run_at.isoformat() if sched.next_run_at else None,
        "nextRunAtIst": iso_ist(sched.next_run_at) if sched.next_run_at else None,
        "lastRunAt": sched.last_run_at.isoformat() if sched.last_run_at else None,
        "lastRunAtIst": iso_ist(sched.last_run_at) if sched.last_run_at else None,
        "lastStatus": sched.last_status,
        "lastError": sched.last_error,
        "lastHistoryId": sched.last_history_id,
    }


# ── Running a schedule ──────────────────────────────────────────────────

def _data_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        r for r in rows
        if "_warning" not in r
        and not r.get("__isSubtotal") and not r.get("__isColumnTotal") and not r.get("__isGrandTotal")
    ]


def run_schedule(db: Session, sched: ReportSchedule) -> Dict[str, Any]:
    """Run one schedule now and record the outcome on it. Never raises
    for report errors — they are stored in last_status / last_error."""
    from app.services.email_service import compose_and_send
    from app.services.pivot_service import build_pivot

    status, error, history_id, rows_sent = "failed", None, None, 0
    try:
        saved = saved_pivot_service.get_saved(db, sched.saved_pivot_id)
        if saved is None:
            raise ScheduleError("The saved pivot for this schedule was deleted.")
        dataset = get_dataset_by_id(db, saved.dataset_id)
        if dataset is None:
            raise ScheduleError("The dataset for this schedule was deleted.")
        pivot_request = saved_pivot_service.to_pivot_request(saved)
        response = build_pivot(db, pivot_request)
        rows = _data_rows(response.rows)
        if not rows:
            if sched.skip_if_empty:
                status, error = "skipped", "The pivot had no rows, so nothing was sent."
                return _finish(db, sched, status, error, None, 0)
            raise ScheduleError("The pivot had no rows to send.")

        req = pivot_request.model_dump(by_alias=True)
        email = EmailSendRequest(
            to=json.loads(sched.to_json or "[]"),
            cc=json.loads(sched.cc_json or "[]"),
            bcc=json.loads(sched.bcc_json or "[]"),
            subject=sched.subject,
            message=sched.message or "",
            datasetId=saved.dataset_id,
            sheetName=saved.sheet_name,
            rows=req.get("rows") or [],
            columns=req.get("columns") or [],
            values=req.get("values") or [],
            filters=req.get("filters") or {},
            dateGrouping=req.get("dateGrouping") or {},
            sorting=req.get("sorting") or {},
            totals=req.get("totals") or {},
            layout=req.get("layout") or "tabular",
            selections=[{"selection": r.get("__rowFields") or {}} for r in rows],
            pivot_rows=rows,
            pivot_response={"columns": response.columns, "totals": response.totals},
            dataset_name=dataset.filename,
        )
        result = compose_and_send(db, email, source="schedule", schedule_id=sched.id)
        status, history_id, rows_sent = "success", result["history_id"], len(rows)
    except Exception as exc:  # noqa: BLE001 — recorded on the schedule
        error = str(exc) or exc.__class__.__name__
        db.rollback()
    return _finish(db, sched, status, error, history_id, rows_sent)


def _finish(db, sched, status, error, history_id, rows_sent) -> Dict[str, Any]:
    sched.last_run_at = datetime.utcnow()
    sched.last_status = status
    sched.last_error = error
    if history_id:
        sched.last_history_id = history_id
    db.commit()
    level = "info" if status != "failed" else "error"
    log_event(level, f"Scheduled report {status}", category="email_sent" if status == "success" else "email_failed",
              details=f"schedule={sched.id} name={sched.name} rows={rows_sent} error={error or ''}")
    return {"status": status, "error": error, "historyId": history_id, "rowsSent": rows_sent}


# ── Background loop ─────────────────────────────────────────────────────

def run_due(now: Optional[datetime] = None) -> int:
    """Run every schedule that is due. Returns how many were run."""
    now = now or datetime.utcnow()
    ran = 0
    db = SessionLocal()
    try:
        due = (
            db.query(ReportSchedule)
            .filter(ReportSchedule.enabled.is_(True))
            .filter(ReportSchedule.next_run_at.isnot(None))
            .filter(ReportSchedule.next_run_at <= now)
            .all()
        )
        for sched in due:
            due_at = sched.next_run_at
            next_at = compute_next_run(sched, now)
            claimed = db.execute(
                update(ReportSchedule)
                .where(ReportSchedule.id == sched.id, ReportSchedule.next_run_at == due_at)
                .values(next_run_at=next_at)
            ).rowcount
            db.commit()
            if claimed != 1:
                continue  # another process took it
            db.refresh(sched)
            if now - due_at > MISSED_GRACE:
                log_event("warning", "Scheduled report missed", category="email_failed",
                          details=f"schedule={sched.id} was due {due_at.isoformat()}Z; skipped")
                continue
            run_schedule(db, sched)
            ran += 1
    finally:
        db.close()
    return ran


_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def _loop() -> None:
    while not _stop.wait(POLL_SECONDS):
        try:
            run_due()
        except Exception:  # keep the loop alive
            logger.exception("Scheduler tick failed")


def start() -> None:
    """Start the background scheduler (no-op if SCHEDULER_ENABLED=0)."""
    global _thread
    if os.environ.get("SCHEDULER_ENABLED", "1").strip() in {"0", "false", "no"}:
        return
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="report-scheduler", daemon=True)
    _thread.start()
    log_event("info", "Report scheduler started", category="startup", details=f"poll={POLL_SECONDS}s")


def stop() -> None:
    _stop.set()


def reschedule_all(db: Session) -> None:
    """Recompute next runs (e.g. after the app timezone changes)."""
    now = datetime.utcnow()
    for sched in db.query(ReportSchedule).filter(ReportSchedule.enabled.is_(True)).all():
        sched.next_run_at = compute_next_run(sched, now)
    db.commit()
