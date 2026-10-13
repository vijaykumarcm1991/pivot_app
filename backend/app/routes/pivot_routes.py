"""
Pivot routes — Phase 3 + 5 + 8.

API endpoints:
  POST /api/pivot                  -> compute pivot output
  POST /api/pivot/validate         -> validate configuration WITHOUT computing
  POST /api/pivot/drilldown        -> return raw rows matching a pivot selection
  POST /api/pivot/delete-records   -> Phase 8 — soft-delete raw records behind
                                       the selected pivot rows

Page:
  GET /pivot                       -> Pivot Builder UI
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
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
from app.services.soft_delete_service import (
    SoftDeleteError,
    count_matching_records,
    soft_delete_from_pivot,
)
from app.services import metadata_cache
from app.services.app_logging import log_event

router = APIRouter()
from app.templating import templates


# ── Phase 8: soft-delete request schema ─────────────────────────────────

class DeleteRecordsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # The pivot request that produced the current result (we re-run
    # the same filter/aggregation context so the source rows are
    # exactly the ones the user sees).
    pivot_request: Dict[str, Any] = Field(alias="pivotRequest")

    # The list of {field: value} selections to delete — one per
    # selected pivot row. The frontend builds these from the
    # row fields of the selected rows.
    selections: List[Dict[str, Any]] = Field(default_factory=list)

    # Phase 8 (safety) — if True, the endpoint counts how many source
    # records would be deleted and returns that count without actually
    # deleting anything.  The frontend uses this to show the user
    # "you are about to delete N records" before they confirm.
    dry_run: bool = Field(default=False, alias="dryRun")


class DeleteRecordsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    audit_id:   int   = Field(alias="auditId")
    matched:    int
    deleted:    int
    selections: int


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


@router.post("/api/pivot/delete-records", response_model=DeleteRecordsResponse, response_model_by_alias=True)
def api_pivot_delete_records(
    payload: DeleteRecordsRequest,
    req: Request,
    db: Session = Depends(get_db),
):
    """
    Phase 8 — soft-delete the raw records behind the selected pivot rows.

    The frontend re-uses the same `pivotRequest` it used to compute
    the pivot, plus a list of `selections` (one per selected pivot
    row). The endpoint returns a small summary so the UI can show
    "X records deleted from Y pivot rows" and trigger an automatic
    pivot refresh.

    If `dryRun: true` is sent, the endpoint counts how many source
    records would be deleted and returns the count without actually
    deleting anything.  The frontend uses this to show the user
    "you are about to delete N records" before they confirm.
    """
    try:
        pr = payload.pivot_request or {}
        ds_id = pr.get("datasetId", pr.get("dataset_id"))
        sheet_name = pr.get("sheetName", pr.get("sheet_name"))
        if ds_id is None or not sheet_name:
            raise SoftDeleteError("Pivot request is missing datasetId / sheetName.")

        # Phase 8 (safety) — dry-run: count the distinct records a delete
        # would hide, using exactly the same matching code as the real
        # delete. Errors are reported, never swallowed into a 0 count.
        if payload.dry_run:
            matched = count_matching_records(
                db, pivot_request=pr, selections=payload.selections,
            )
            return DeleteRecordsResponse(
                auditId=0,
                matched=matched,
                deleted=0,
                selections=len(payload.selections),
            )

        result = soft_delete_from_pivot(
            db,
            dataset_id=int(ds_id),
            sheet_name=sheet_name,
            pivot_request=pr,
            selections=payload.selections,
            actor="ui",
        )
        metadata_cache.invalidate_dataset(int(ds_id))
        log_event(
            "info",
            "Pivot records delete requested",
            category="pivot_delete",
            details=f"dataset_id={ds_id} selections={len(payload.selections)} deleted={result['deleted']}",
            request=req,
        )
        return DeleteRecordsResponse(
            auditId=result["audit_id"],
            matched=result["matched"],
            deleted=result["deleted"],
            selections=result["selections"],
        )
    except SoftDeleteError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log_event("error", "Pivot records delete failed", category="pivot_delete",
                  details=str(exc), request=req)
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}") from exc
