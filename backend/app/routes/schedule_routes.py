"""
Scheduled reports API + page.

  GET    /reports                       page
  GET    /api/schedules                 list
  POST   /api/schedules                 create
  GET    /api/schedules/{id}            detail
  PUT    /api/schedules/{id}            update
  DELETE /api/schedules/{id}            delete
  POST   /api/schedules/{id}/run        run now (synchronous)
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.report_schedule import ReportSchedule
from app.services import scheduler_service as svc
from app.services.app_logging import log_event
from app.templating import templates

router = APIRouter()


def _get_or_404(db: Session, schedule_id: int) -> ReportSchedule:
    row = db.query(ReportSchedule).filter(ReportSchedule.id == schedule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return row


@router.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    return templates.TemplateResponse("reports.html", {"request": request})


@router.get("/api/schedules")
def api_list(db: Session = Depends(get_db)):
    rows = db.query(ReportSchedule).order_by(ReportSchedule.name.asc()).all()
    return [svc.serialize(db, r) for r in rows]


@router.get("/api/schedules/{schedule_id}")
def api_get(schedule_id: int, db: Session = Depends(get_db)):
    return svc.serialize(db, _get_or_404(db, schedule_id))


@router.post("/api/schedules", status_code=201)
def api_create(payload: Dict[str, Any], db: Session = Depends(get_db)):
    sched = ReportSchedule()
    try:
        svc.apply_fields(db, sched, payload or {})
    except svc.ScheduleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.add(sched)
    db.commit()
    db.refresh(sched)
    log_event("info", "Scheduled report created", category="general", details=f"id={sched.id} name={sched.name}")
    return svc.serialize(db, sched)


@router.put("/api/schedules/{schedule_id}")
def api_update(schedule_id: int, payload: Dict[str, Any], db: Session = Depends(get_db)):
    sched = _get_or_404(db, schedule_id)
    try:
        svc.apply_fields(db, sched, payload or {})
    except svc.ScheduleError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(sched)
    return svc.serialize(db, sched)


@router.delete("/api/schedules/{schedule_id}")
def api_delete(schedule_id: int, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, schedule_id))
    db.commit()
    return {"deleted": schedule_id}


@router.post("/api/schedules/{schedule_id}/run")
def api_run_now(schedule_id: int, db: Session = Depends(get_db)):
    sched = _get_or_404(db, schedule_id)
    result = svc.run_schedule(db, sched)
    db.refresh(sched)
    return {**result, "schedule": svc.serialize(db, sched)}
