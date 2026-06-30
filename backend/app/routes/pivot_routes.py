"""
Pivot routes — Phase 3.

API endpoints:
  POST /api/pivot             -> compute pivot output
  POST /api/pivot/validate    -> validate configuration WITHOUT computing
  POST /api/pivot/drilldown   -> return raw rows matching a pivot selection

Page:
  GET /pivot                  -> Pivot Builder UI
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.schemas.pivot import (
    PivotDrilldownRequest,
    PivotDrilldownResponse,
    PivotRequest,
    PivotResponse,
    PivotValidateRequest,
    PivotValidateResponse,
)
from app.services.pivot_service import PivotError, build_drilldown, build_pivot
from app.services.pivot_validation_service import validate_pivot

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/pivot", response_class=HTMLResponse)
async def pivot_page(request: Request):
    """Render the Pivot Builder UI."""
    return templates.TemplateResponse("pivot.html", {"request": request})


@router.post("/api/pivot/validate", response_model=PivotValidateResponse)
def api_pivot_validate(
    request: PivotValidateRequest, db: Session = Depends(get_db)
):
    """
    Validate a pivot configuration against stored dataset metadata.
    This endpoint does NOT load the sheet or compute the pivot.
    """
    result = validate_pivot(db, request)
    return PivotValidateResponse(**result)


@router.post("/api/pivot", response_model=PivotResponse)
def api_pivot(request: PivotRequest, db: Session = Depends(get_db)):
    """Compute a pivot table on the backend using pandas."""
    try:
        return build_pivot(db, request)
    except PivotError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/pivot/drilldown", response_model=PivotDrilldownResponse)
def api_pivot_drilldown(
    request: PivotDrilldownRequest, db: Session = Depends(get_db)
):
    """Return raw source rows matching a pivot cell selection."""
    try:
        return build_drilldown(db, request)
    except PivotError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
