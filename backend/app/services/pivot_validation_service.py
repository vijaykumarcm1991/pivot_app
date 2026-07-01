"""
Pivot validation service — Phase 3.

Validates a PivotRequest against the dataset metadata stored in the database
WITHOUT loading the actual sheet contents. This is what the Phase 3 endpoint
`POST /api/pivot/validate` returns — a clean validation response that the
frontend can use before asking the backend to compute anything (Phase 4).

Validation rules:
  - dataset must exist
  - sheet must exist for the dataset
  - every row, column, value, filter, and date-grouping field must exist
    in the sheet
  - aggregation must be one of: count | sum | average | min | max
  - date grouping must be one of: year | quarter | month | week | day
  - layout must be: compact | tabular
  - value field aggregation vs. datatype rules:
      * Text/Boolean → only "count" allowed
      * Numeric (integer/decimal) → all aggregations allowed
      * Date → all aggregations allowed
"""
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.config.settings import (
    MAX_PIVOT_RESULT_ROWS,
    MAX_ROWS_ALLOWED,
    MAX_COLUMNS_ALLOWED,
)
from app.repositories.dataset_repository import get_dataset_by_id
from app.repositories.sheet_repository import get_sheet, get_sheets_by_dataset
from app.repositories.column_repository import get_columns_by_sheet
from app.schemas.pivot import PivotRequest, PivotValue
from app.services.pivot_service import (
    AGGREGATIONS,
    DATE_GROUPS,
    PivotError,
)


# ---------------------------------------------------------------------------
# Constants — exported so the UI can ask for valid aggregations per type
# ---------------------------------------------------------------------------

NUMERIC_TYPES = {"integer", "float", "decimal"}
TEXT_TYPES    = {"string", "text"}
BOOL_TYPES    = {"boolean"}
DATE_TYPES    = {"datetime", "date"}


def valid_aggregations_for(data_type: str) -> List[str]:
    """Return aggregations appropriate for a column data type."""
    if data_type in TEXT_TYPES or data_type in BOOL_TYPES:
        return ["count"]
    if data_type in NUMERIC_TYPES or data_type in DATE_TYPES:
        return ["count", "sum", "average", "min", "max"]
    return ["count"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# ── Phase 7 — Display Options validation ─────────────────────────────────
ALLOWED_NUMBER_FORMATS = {"integer", "decimal", "currency", "percentage", "thousands"}
ALLOWED_DATE_FORMATS   = {"yyyy-mm-dd", "dd-mm-yyyy", "MMM yyyy", "MMMM yyyy", "quarter", "year"}
ALLOWED_COND_TYPES     = {"gt", "lt", "eq", "top10", "bottom10", "duplicates"}


def _validate_display_options(display_options, col_names, errors, warnings):
    """Phase 7 — validate the optional DisplayOptions block.  Adds to
    `errors` and `warnings` in place.  Returns nothing; failures don't
    short-circuit (the user gets every error at once)."""
    if not display_options:
        return

    # numberFormat / dateFormat
    nf = dict(display_options.number_format or {})
    df = dict(display_options.date_format or {})
    for field, fmt in nf.items():
        if field not in col_names:
            errors.append(f"Display number format: field '{field}' not in sheet.")
        elif fmt not in ALLOWED_NUMBER_FORMATS:
            errors.append(
                f"Display number format: unsupported value '{fmt}' "
                f"for field '{field}'. Allowed: {sorted(ALLOWED_NUMBER_FORMATS)}."
            )
    for field, fmt in df.items():
        if field not in col_names:
            errors.append(f"Display date format: field '{field}' not in sheet.")
        elif fmt not in ALLOWED_DATE_FORMATS:
            errors.append(
                f"Display date format: unsupported value '{fmt}' "
                f"for field '{field}'. Allowed: {sorted(ALLOWED_DATE_FORMATS)}."
            )

    # conditionalFormats
    for cf in (display_options.conditional_formats or []):
        if not cf.field:
            errors.append("Conditional format: missing 'field'.")
            continue
        if cf.field not in col_names:
            errors.append(f"Conditional format: field '{cf.field}' not in sheet.")
        if cf.type not in ALLOWED_COND_TYPES:
            errors.append(
                f"Conditional format: unsupported type '{cf.type}' "
                f"for field '{cf.field}'. Allowed: {sorted(ALLOWED_COND_TYPES)}."
            )
        if cf.type in {"gt", "lt", "eq"} and cf.value is None:
            errors.append(
                f"Conditional format: '{cf.type}' rule for '{cf.field}' "
                f"requires a numeric 'value'."
            )

    # frozenColumns / hiddenColumns
    for col in (display_options.frozen_columns or []):
        if col not in col_names:
            errors.append(f"Display frozen column: '{col}' not in sheet.")
    for col in (display_options.hidden_columns or []):
        if col not in col_names:
            errors.append(f"Display hidden column: '{col}' not in sheet.")


def validate_pivot(db: Session, request: PivotRequest) -> Dict[str, Any]:
    """
    Validate *request* and return a structured response.

    Returns:
        {
            "valid": bool,
            "errors": List[str],          # one entry per failed rule
            "warnings": List[str],        # non-fatal issues
            "summary": {                  # short description of the config
                "dataset": str,
                "sheet":   str,
                "rows":    List[str],
                "columns": List[str],
                "values":  List[Dict[str, str]],
                "filters": Dict[str, Any],
                "date_grouping": Dict[str, str],
                "layout":  str,
            },
            "per_value_field": {          # one entry per value field
                field_name: {
                    "data_type": str,
                    "allowed_aggregations": List[str],
                }
            }
        }
    """
    errors:   List[str] = []
    warnings: List[str] = []
    summary:  Dict[str, Any] = {}
    per_value: Dict[str, Any] = {}

    # --- 1. dataset must exist ---------------------------------------------
    dataset = get_dataset_by_id(db, request.dataset_id)
    if not dataset:
        return _build_response(False, [f"Dataset {request.dataset_id} not found"], [], {}, {})

    summary["dataset"] = dataset.filename
    summary["sheet"]   = request.sheet_name
    summary["rows"]    = list(request.rows)
    summary["columns"] = list(request.columns)
    summary["filters"] = dict(request.filters)
    summary["date_grouping"] = dict(request.date_grouping)
    summary["layout"]  = request.layout

    # --- 2. layout ---------------------------------------------------------
    if request.layout not in {"compact", "tabular"}:
        errors.append(
            f"Invalid layout '{request.layout}'. Supported: 'compact', 'tabular'."
        )
    summary["layout"] = request.layout

    # --- 3. sheet must exist ----------------------------------------------
    sheet = get_sheet(db, request.dataset_id, request.sheet_name)
    if not sheet:
        sheets = get_sheets_by_dataset(db, request.dataset_id)
        names  = ", ".join(s.sheet_name for s in sheets) or "<none>"
        errors.append(
            f"Sheet '{request.sheet_name}' not found in dataset "
            f"'{dataset.filename}'. Available: {names}."
        )
        # Cannot continue without sheet metadata
        return _build_response(False, errors, warnings, summary, per_value)

    # --- 4. build a column-name → ColumnInfo map ---------------------------
    columns_db = get_columns_by_sheet(db, request.dataset_id, request.sheet_name)
    col_info: Dict[str, Any] = {c.column_name: c for c in columns_db}
    col_names = set(col_info.keys())

    def _check_field(field: str, kind: str) -> None:
        if field not in col_names:
            errors.append(f"{kind} field '{field}' not found in sheet '{sheet.sheet_name}'.")

    for f in request.rows:
        _check_field(f, "Row")
    for f in request.columns:
        _check_field(f, "Column")
    for f in request.filters.keys():
        _check_field(f, "Filter")

    # --- 5. values & aggregations ------------------------------------------
    values_summary: List[Dict[str, str]] = []
    raw_values = request.values or []
    value_specs: List[PivotValue] = []

    if not raw_values:
        # Default value: count of first column — the engine handles this
        # automatically. We mark it as a warning so the UI knows.
        warnings.append(
            "No value fields specified. The engine will default to 'count' of the first column."
        )
        if col_names:
            first_col = next(iter(col_names))
            value_specs.append(
                PivotValue(field=first_col, aggregation="count", label="count")
            )
    else:
        for item in raw_values:
            spec = _coerce_value(item)
            if spec.aggregation.lower() not in AGGREGATIONS:
                errors.append(
                    f"Unsupported aggregation '{spec.aggregation}' for field '{spec.field}'. "
                    f"Supported: {', '.join(sorted(AGGREGATIONS.keys()))}."
                )
                continue
            spec.aggregation = spec.aggregation.lower()
            if spec.field not in col_names:
                errors.append(
                    f"Value field '{spec.field}' not found in sheet '{sheet.sheet_name}'."
                )
                continue

            dt = col_info[spec.field].data_type
            allowed = valid_aggregations_for(dt)
            if spec.aggregation not in allowed:
                errors.append(
                    f"Field '{spec.field}' has data type '{dt}'; "
                    f"aggregation '{spec.aggregation}' is not allowed. "
                    f"Allowed: {', '.join(allowed)}."
                )

            values_summary.append(
                {"field": spec.field, "aggregation": spec.aggregation, "label": spec.label or f"{spec.aggregation}_{spec.field}"}
            )
            per_value[spec.field] = {
                "data_type": dt,
                "allowed_aggregations": allowed,
            }
            value_specs.append(spec)

    summary["values"] = values_summary

    # --- 6. date grouping --------------------------------------------------
    for f, grp in request.date_grouping.items():
        if f not in col_names:
            errors.append(f"Date-grouping field '{f}' not found in sheet '{sheet.sheet_name}'.")
        if grp not in DATE_GROUPS:
            errors.append(
                f"Unsupported date grouping '{grp}' for field '{f}'. "
                f"Supported: {', '.join(sorted(DATE_GROUPS))}."
            )
        if f in col_info and col_info[f].data_type not in DATE_TYPES:
            warnings.append(
                f"Date grouping is applied to '{f}', but its data type is "
                f"'{col_info[f].data_type}' (not a date column)."
            )

    # --- 7. rough size sanity check ----------------------------------------
    if sheet.row_count > MAX_ROWS_ALLOWED:
        warnings.append(
            f"Sheet '{sheet.sheet_name}' has {sheet.row_count:,} rows, which exceeds the "
            f"recommended limit of {MAX_ROWS_ALLOWED:,}. Apply filters before computing."
        )
    if len(col_names) > MAX_COLUMNS_ALLOWED:
        warnings.append(
            f"Sheet '{sheet.sheet_name}' has {len(col_names):,} columns, which exceeds "
            f"the recommended limit of {MAX_COLUMNS_ALLOWED:,}."
        )

    # --- 8. per-row sorting entries (if any) -------------------------------
    for field, direction in (request.sorting or {}).items():
        if field not in col_names:
            errors.append(f"Sort field '{field}' not found in sheet '{sheet.sheet_name}'.")
        if direction not in {"asc", "desc", "ascending", "descending"}:
            errors.append(
                f"Invalid sort direction '{direction}' for field '{field}'. "
                "Use 'asc' or 'desc'."
            )

    # --- 9. Phase 7 — display options --------------------------------------
    if getattr(request, "display_options", None):
        _validate_display_options(request.display_options, col_names, errors, warnings)

    return _build_response(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        summary=summary,
        per_value=per_value,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce_value(item: Any) -> PivotValue:
    """Turn a value entry (str | dict | PivotValue) into a PivotValue."""
    if isinstance(item, PivotValue):
        return item
    if isinstance(item, str):
        return PivotValue(field=item, aggregation="sum")
    if isinstance(item, dict):
        return PivotValue(**item)
    raise PivotError(f"Invalid values entry: {item!r}")


def _build_response(
    valid: bool,
    errors: List[str],
    warnings: List[str],
    summary: Dict[str, Any],
    per_value: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "valid":           valid,
        "errors":          errors,
        "warnings":        warnings,
        "summary":         summary,
        "per_value_field": per_value,
    }
