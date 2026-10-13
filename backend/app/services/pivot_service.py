"""
Phase 3 + Phase 7 pivot engine.

The backend is the authoritative pivot calculator. The frontend should send a
pivot definition and render this service's output without recalculating it.

Phase 7 adds:
  - `displayOptions` (number/date formats, conditional formats, frozen
    columns, hidden columns)
  - `totals.repeatItemLabels` (Tabular Form: fill blank grouped cells)
  - `totals.showSubtotals` (real subtotal rows after each group)
  - `totals.showColumnTotals` (a per-column-total pinned row beneath
    the grand total)
  - Hierarchy markers on every response row:
      __level        : 0..N  (0 = top-most group)
      __parentKey    : concatenated values of all parent row fields
      __isSubtotal   : bool
      __isColumnTotal: bool
    The frontend uses these to drive expand/collapse, subtotal styling,
    and the column-totals row without recomputing anything.

NOTE: Phase 3 also exposes a separate validation endpoint
(`POST /api/pivot/validate`, see `pivot_validation_service.py`) that validates a
request against stored metadata without ever loading the file.
"""

import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from app.config.settings import UPLOAD_DIR, MAX_ROWS_ALLOWED, MAX_COLUMNS_ALLOWED, MAX_PIVOT_RESULT_ROWS, MAX_PIVOT_MEMORY_MB
from app.repositories.dataset_repository import get_dataset_by_id
from app.schemas.pivot import (
    DisplayOptions,
    PivotDrilldownRequest,
    PivotDrilldownResponse,
    PivotRequest,
    PivotResponse,
    PivotMetadata,
    PivotValue,
    TotalsOptions,
)
from app.services import metadata_cache
from app.services.excel_service import load_sheet_df
from app.services.row_keys import frame_row_keys
from app.utils.file_utils import build_upload_path


AGGREGATIONS = {
    "count": "count",
    "sum": "sum",
    "average": "mean",
    "min": "min",
    "max": "max",
}

DATE_GROUPS = {"year", "quarter", "month", "week", "day"}

# Placeholder for null values in row / column group fields. Mirrors
# Excel's behaviour — null values in a row field show as "(blank)" rather
# than being excluded from the pivot.
NULL_PLACEHOLDER = "(blank)"


class PivotError(ValueError):
    """Raised when a pivot request is invalid or cannot be computed."""


def _validate_dataset_size(df: pd.DataFrame) -> None:
    """Validate that the dataset is within acceptable size limits."""
    rows, cols = df.shape

    if rows > MAX_ROWS_ALLOWED:
        raise PivotError(
            f"Dataset has {rows:,} rows, which exceeds the maximum allowed ({MAX_ROWS_ALLOWED:,}). "
            "Please apply filters to reduce the dataset size or use a smaller dataset."
        )

    if cols > MAX_COLUMNS_ALLOWED:
        raise PivotError(
            f"Dataset has {cols:,} columns, which exceeds the maximum allowed ({MAX_COLUMNS_ALLOWED:,}). "
            "Please select fewer columns for analysis."
        )

    # Estimate memory usage (approximate)
    estimated_mb = (df.memory_usage(deep=True).sum() / 1024 / 1024)
    if estimated_mb > MAX_PIVOT_MEMORY_MB:
        raise PivotError(
            f"Dataset requires approximately {estimated_mb:.1f} MB of memory, "
            f"which exceeds the limit of {MAX_PIVOT_MEMORY_MB} MB. "
            "Please apply filters to reduce the dataset size."
        )


def _validate_layout(layout: str) -> None:
    if layout not in {"compact", "tabular"}:
        raise PivotError(f"Unsupported layout: {layout}")


def _is_truthy(v: Any) -> bool:
    """Coerce a (sometimes-string) flag to bool — pydantic / frontend may
    send `"false"` as a string when round-tripping through JSON."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "on"}
    return bool(v)


def build_pivot(db: Session, request: PivotRequest) -> PivotResponse:
    """Compute a pivot table from an uploaded dataset sheet."""
    _validate_layout(request.layout)
    df = _load_dataset_sheet(db, request.dataset_id, request.sheet_name)

    # Validate dataset size before processing
    _validate_dataset_size(df)

    source_rows = len(df)
    value_specs = _normalise_values(request.values, df)
    group_rows, group_columns, grouped_labels = _prepare_group_fields(df, request)
    filtered_df = _apply_filters(df, request.filters)
    filtered_rows = len(filtered_df)

    totals_opts: TotalsOptions = request.totals or TotalsOptions()
    display_opts: DisplayOptions = request.display_options or DisplayOptions()

    if filtered_df.empty:
        rows: List[Dict[str, Any]] = []
        pivot_columns = _visible_columns(
            _display_row_columns(group_rows, grouped_labels, request.layout),
            value_specs,
            [],
        )
    else:
        rows, pivot_columns = _compute_pivot_rows(
            filtered_df,
            group_rows,
            group_columns,
            grouped_labels,
            value_specs,
            request.layout,
            sorting=request.sorting,
            show_subtotals=bool(totals_opts.show_subtotals),
        )

        if totals_opts.show_column_totals and group_rows:
            _insert_column_total_row(
                rows, filtered_df, group_rows, group_columns, grouped_labels,
                value_specs, pivot_columns, request.layout,
            )

    if totals_opts.repeat_item_labels and group_rows and request.layout != "compact":
        _apply_repeat_item_labels(rows, [_display_group_name(f, grouped_labels) for f in group_rows])

    totals = _compute_totals(filtered_df, value_specs, rows, totals_opts)
    if not totals_opts.show_row_totals:
        pivot_columns = [c for c in pivot_columns if c != "row_total"]

    # With column groups the grid's grand-total row is keyed by the
    # per-column names ("sum_Amount | Open"), so add the grand total of
    # every column (and of row_total) — previously these cells were "—".
    if totals_opts.show_grand_totals and group_columns and not filtered_df.empty:
        per_column = _pivot_frame(filtered_df, [], group_columns, value_specs, grouped_labels)
        if len(per_column):
            totals["grand"].update(_df_to_records(per_column)[0])
        if "row_total" in pivot_columns and len(value_specs) == 1:
            totals["grand"]["row_total"] = totals["grand"].get(_value_label(value_specs[0]))

    return PivotResponse(
        rows=rows,
        columns=pivot_columns,
        totals=totals,
        metadata=PivotMetadata(
            dataset_id=request.dataset_id,
            sheet_name=request.sheet_name,
            source_rows=source_rows,
            filtered_rows=filtered_rows,
            layout=request.layout,
            rows=request.rows,
            columns=request.columns,
            date_grouping=request.date_grouping,
            sorting=dict(request.sorting or {}),
            totals=totals_opts,
            display_options=display_opts,
        ),
        aggregations=[
            {
                "field": spec.field,
                "aggregation": spec.aggregation,
                "label": _value_label(spec),
            }
            for spec in value_specs
        ],
    )


# ── Selection matching (drilldown / soft delete / email) ────────────────

def _drilldown_request_for(base: PivotRequest, selection: Dict[str, Any], limit: int) -> PivotDrilldownRequest:
    data = base.model_dump(by_alias=True) if hasattr(base, "model_dump") else dict(base)
    data.pop("selection", None)
    data.pop("limit", None)
    return PivotDrilldownRequest(**data, selection=selection or {}, limit=limit)


def match_selections(
    db: Session, request: PivotRequest, selections: List[Dict[str, Any]]
) -> pd.DataFrame:
    """
    Return the raw source rows (after soft-delete + filters) represented
    by the union of `selections` — one {field: value} map per pivot row.

    The sheet is loaded once for all selections and rows are deduplicated
    by their position in the source, so overlapping selections are never
    double-counted and genuinely identical records are never collapsed.
    No row limit is applied; callers cap the output themselves.
    """
    _validate_layout(request.layout)
    df = _load_dataset_sheet(db, request.dataset_id, request.sheet_name)
    _, _, grouped_labels = _prepare_group_fields(df, request)
    filtered_df = _apply_filters(df, request.filters)
    allow_empty = not request.rows

    keep = pd.Series(False, index=filtered_df.index)
    for selection in selections:
        matched = _apply_selection(filtered_df, selection or {}, grouped_labels, allow_empty=allow_empty)
        keep.loc[matched.index] = True
    return filtered_df.loc[keep]


def build_drilldown(
    db: Session, request: PivotDrilldownRequest
) -> PivotDrilldownResponse:
    """Return raw rows matching a pivot cell selection."""
    matched_df = match_selections(db, request, [request.selection])
    cap = max(1, min(request.limit, 5000))
    limited_df = matched_df.head(cap)

    return PivotDrilldownResponse(
        rows=_df_to_records(limited_df),
        columns=[str(c) for c in limited_df.columns if not str(c).startswith("__pivot_")],
        metadata={
            "dataset_id": request.dataset_id,
            "sheet_name": request.sheet_name,
            "matched_rows": int(len(matched_df)),
            "returned_rows": int(len(limited_df)),
            "limit": int(cap),
            "selection": request.selection,
        },
    )


def build_drilldown_multi(
    db: Session,
    dataset_id: int,
    sheet_name: str,
    rows: List[str],
    columns: List[str],
    values: List[Any],
    filters: Dict[str, Any],
    date_grouping: Dict[str, str],
    sorting: Dict[str, str],
    totals: Any,
    layout: str,
    selections: List[Dict[str, Any]],
    limit: int = 5000,
) -> Dict[str, Any]:
    """
    Multi-selection drilldown used by the email attachment.

    Returns the union of the raw records behind every selection (each
    source record at most once) in source order, capped at `limit`.
    `matched_rows` is the true number of distinct matching records.
    """
    cap = max(1, int(limit))
    if not selections:
        return {
            "rows": [],
            "columns": [],
            "metadata": {
                "dataset_id": dataset_id,
                "sheet_name": sheet_name,
                "matched_rows": 0,
                "returned_rows": 0,
                "limit": cap,
                "selections": [],
            },
        }

    if hasattr(totals, "model_dump"):
        totals = totals.model_dump(by_alias=True)
    request = PivotRequest(
        dataset_id=dataset_id,
        sheet_name=sheet_name,
        rows=rows,
        columns=columns,
        values=values,
        filters=filters,
        date_grouping=date_grouping,
        sorting=sorting,
        totals=totals or {},
        layout=layout,
    )
    matched_df = match_selections(db, request, selections)
    limited_df = matched_df.head(cap)
    out_rows = _df_to_records(limited_df)

    return {
        "rows": out_rows,
        "columns": [str(c) for c in limited_df.columns if not str(c).startswith("__pivot_")],
        "metadata": {
            "dataset_id": dataset_id,
            "sheet_name": sheet_name,
            "matched_rows": int(len(matched_df)),
            "returned_rows": len(out_rows),
            "limit": cap,
            "selections": list(selections),
        },
    }


# ── Dataset loading (with soft-delete filter + in-process cache) ────────

def _soft_deleted_keys(db: Session, dataset_id: int, sheet_name: str) -> set:
    from app.models.soft_deleted_record import SoftDeletedRecord

    rows = (
        db.query(SoftDeletedRecord.source_key)
        .filter(SoftDeletedRecord.dataset_id == dataset_id)
        .filter(SoftDeletedRecord.sheet_name == sheet_name)
        .all()
    )
    return {r[0] for r in rows if r[0]}


def _soft_deleted_count(db: Session, dataset_id: int, sheet_name: str) -> int:
    from sqlalchemy import func
    from app.models.soft_deleted_record import SoftDeletedRecord

    return int(
        db.query(func.count(SoftDeletedRecord.id))
        .filter(SoftDeletedRecord.dataset_id == dataset_id)
        .filter(SoftDeletedRecord.sheet_name == sheet_name)
        .scalar()
        or 0
    )


def _load_dataset_sheet(db: Session, dataset_id: int, sheet_name: str) -> pd.DataFrame:
    """
    Load a sheet as a DataFrame with every soft-deleted record removed.

    The parsed + filtered frame is cached in-process keyed by
    (dataset, sheet) and validated against the file's mtime and the
    number of soft-deleted rows, so repeated pivots / drilldowns don't
    re-parse the workbook. A fresh copy is returned every time because
    callers add helper columns to it.
    """
    dataset = get_dataset_by_id(db, dataset_id)
    if not dataset:
        raise PivotError("Dataset not found")

    filepath = build_upload_path(dataset.stored_filename, UPLOAD_DIR)
    try:
        mtime = os.path.getmtime(filepath)
    except OSError as exc:
        raise PivotError("Uploaded file not found on disk") from exc

    deleted_count = _soft_deleted_count(db, dataset_id, sheet_name)
    stamp = (mtime, deleted_count)
    cached = metadata_cache.get_drilldown_df(dataset_id, sheet_name)
    if cached is not None and cached[0] == stamp:
        return cached[1].copy()

    try:
        df = load_sheet_df(filepath, sheet_name)
    except FileNotFoundError as exc:
        raise PivotError("Uploaded file not found on disk") from exc
    except Exception as exc:
        raise PivotError(f"Failed to load sheet: {exc}") from exc

    df.columns = df.columns.astype(str)

    # Phase 8 — soft delete. Drop every row whose signature is in the
    # soft-deleted table for this (dataset, sheet). Writer and reader
    # both use `frame_row_keys`, so the keys always agree.
    if deleted_count:
        skip = _soft_deleted_keys(db, dataset_id, sheet_name)
        if skip:
            keys = frame_row_keys(df)
            mask = [k not in skip for k in keys]
            df = df.loc[mask].reset_index(drop=True)

    metadata_cache.set_drilldown_df(dataset_id, sheet_name, (stamp, df))
    return df.copy()


def _normalise_values(values: List[Any], df: pd.DataFrame) -> List[PivotValue]:
    if not values:
        return [PivotValue(field=str(df.columns[0]), aggregation="count", label="count")]

    result: List[PivotValue] = []
    seen_labels: set = set()
    for item in values:
        if isinstance(item, PivotValue):
            spec = item.model_copy()
        elif isinstance(item, str):
            spec = PivotValue(field=item, aggregation="sum")
        elif isinstance(item, dict):
            spec = PivotValue(**item)
        else:
            raise PivotError("Invalid values entry")

        spec.aggregation = spec.aggregation.lower()
        if spec.aggregation not in AGGREGATIONS:
            raise PivotError(f"Unsupported aggregation: {spec.aggregation}")
        if spec.field not in df.columns:
            raise PivotError(f"Value field not found: {spec.field}")
        # The same field + aggregation twice would produce two columns
        # with the same name — keep the first one only.
        label = _value_label(spec)
        if label in seen_labels:
            continue
        seen_labels.add(label)
        result.append(spec)

    return result


def _prepare_group_fields(
    df: pd.DataFrame, request: PivotRequest
) -> Tuple[List[str], List[str], Dict[str, str]]:
    grouped_labels: Dict[str, str] = {}
    requested_fields = list(request.rows) + list(request.columns)

    for field in requested_fields:
        if field not in df.columns:
            raise PivotError(f"Group field not found: {field}")

    for field, grouping in request.date_grouping.items():
        if grouping not in DATE_GROUPS:
            raise PivotError(f"Unsupported date grouping: {grouping}")
        if field not in df.columns:
            raise PivotError(f"Date grouping field not found: {field}")
        helper_name = _date_group_field(field, grouping)
        grouped_labels[field] = helper_name
        df[helper_name] = _date_group_series(df[field], grouping)

    group_rows = [_group_field_name(field, grouped_labels) for field in request.rows]
    group_columns = [_group_field_name(field, grouped_labels) for field in request.columns]
    return group_rows, group_columns, grouped_labels


def _is_blank_filter_value(value: Any) -> bool:
    return value is None or value == NULL_PLACEHOLDER


def _isin_with_nulls(series: pd.Series, values: List[Any]) -> pd.Series:
    """`Series.isin` that also treats None / "(blank)" as "cell is empty".

    Plain `isin([None])` never matches pandas NaN / NaT, so a filter on
    the "(blank)" value used to match nothing."""
    wants_blank = any(_is_blank_filter_value(v) for v in values)
    concrete = [v for v in values if not _is_blank_filter_value(v)]
    mask = series.isin(_coerce_filter_values(series, concrete)) if concrete else pd.Series(False, index=series.index)
    if wants_blank:
        mask = mask | series.isna()
    return mask


def _apply_filters(df: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
    filtered = df
    for field, expected in (filters or {}).items():
        if field not in filtered.columns:
            raise PivotError(f"Filter field not found: {field}")

        if isinstance(expected, dict):
            filtered = _apply_structured_filter(filtered, field, expected)
        elif isinstance(expected, list):
            filtered = filtered[_isin_with_nulls(filtered[field], expected)]
        else:
            filtered = filtered[_isin_with_nulls(filtered[field], [expected])]

    return filtered


def _coerce_filter_values(series: pd.Series, values: List[Any]) -> List[Any]:
    """Restore JSON date values to timestamps before exact-match filtering."""
    if pd.api.types.is_datetime64_any_dtype(series):
        out = []
        for value in values:
            try:
                out.append(pd.to_datetime(value) if value is not None else value)
            except (ValueError, TypeError):
                out.append(value)
        return out
    return values


def _apply_structured_filter(
    df: pd.DataFrame, field: str, filter_def: Dict[str, Any]
) -> pd.DataFrame:
    series = df[field]
    if "in" in filter_def:
        return df[_isin_with_nulls(series, list(filter_def["in"] or []))]
    if "notIn" in filter_def:
        return df[~_isin_with_nulls(series, list(filter_def["notIn"] or []))]
    if "equals" in filter_def:
        return df[_isin_with_nulls(series, [filter_def["equals"]])]
    if "contains" in filter_def:
        return df[series.astype(str).str.contains(str(filter_def["contains"]), case=False, na=False, regex=False)]

    try:
        comparable = pd.to_datetime(series) if series.dtype == object else series
    except (ValueError, TypeError):
        comparable = series
    if "from" in filter_def:
        comparable_from = _coerce_comparison_value(comparable, filter_def["from"])
        df = df[comparable >= comparable_from]
        comparable = comparable.loc[df.index]
    if "to" in filter_def:
        comparable_to = _coerce_comparison_value(comparable, filter_def["to"])
        df = df[comparable <= comparable_to]

    return df


# ── Core aggregation ─────────────────────────────────────────────────────

def _fill_group_nulls(df: pd.DataFrame, fields: List[str]) -> pd.DataFrame:
    """Replace nulls in group fields with "(blank)" (Excel behaviour) so
    blank values form their own group instead of being dropped."""
    out = df
    copied = False
    for col in fields:
        if out[col].isna().any():
            if not copied:
                out = out.copy()
                copied = True
            out[col] = out[col].astype(object).where(out[col].notna(), NULL_PLACEHOLDER)
    return out


def _pivot_frame(
    df: pd.DataFrame,
    index: List[str],
    columns: List[str],
    value_specs: List[PivotValue],
    grouped_labels: Dict[str, str],
) -> pd.DataFrame:
    """
    Aggregate `df` by `index` (rows) × `columns` (column groups) for every
    value spec and return a flat frame:

      - one column per index field, named with its display name
      - one column per value spec, named with its label — or, when
        column groups are present, `"<label> | <col value> | ..."`

    `count` / `sum` cells for missing combinations are 0 (Excel shows
    blank but 0 is what the previous engine returned); `average` / `min`
    / `max` cells stay null rather than pretending to be 0.

    An empty `index` produces a single row (the overall aggregate).
    """
    work = df
    idx = list(index)
    synthetic = not idx
    if synthetic:
        work = work.assign(__all__=0)
        idx = ["__all__"]
    work = _fill_group_nulls(work, idx + list(columns))

    named = {
        f"__v{i}": (spec.field, AGGREGATIONS[spec.aggregation])
        for i, spec in enumerate(value_specs)
    }
    try:
        grouped = work.groupby(idx + list(columns), sort=True, dropna=False, observed=True).agg(**named)
    except MemoryError as exc:
        raise PivotError(
            "Pivot computation ran out of memory. Please reduce dataset size, "
            "select fewer grouping fields, or apply filters."
        ) from exc
    except TypeError as exc:
        raise PivotError(f"Could not aggregate values: {exc}") from exc

    labels = {f"__v{i}": _value_label(spec) for i, spec in enumerate(value_specs)}
    additive = {f"__v{i}" for i, spec in enumerate(value_specs) if spec.aggregation in {"count", "sum"}}

    if columns:
        wide = grouped.unstack(list(columns))
        flat_names = []
        fill_zero = []
        for col in wide.columns:
            vname, *col_values = col if isinstance(col, tuple) else (col,)
            name = " | ".join([labels[vname]] + [str(v) for v in col_values])
            flat_names.append(name)
            if vname in additive:
                fill_zero.append(name)
        wide.columns = flat_names
        if fill_zero:
            wide[fill_zero] = wide[fill_zero].fillna(0)
        out = wide
    else:
        out = grouped.rename(columns=labels)

    out = out.reset_index()
    if synthetic:
        out = out.drop(columns=["__all__"])
    return _rename_group_columns(out, grouped_labels)


def _sort_key(series: pd.Series) -> pd.Series:
    """Sort key that tolerates mixed types and puts "(blank)" last."""
    def key(v):
        if v is None or v == NULL_PLACEHOLDER or (isinstance(v, float) and pd.isna(v)):
            return (2, "")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return (0, v)
        return (1, str(v))
    return series.map(key)


def _compute_pivot_rows(
    df: pd.DataFrame,
    group_rows: List[str],
    group_columns: List[str],
    grouped_labels: Dict[str, str],
    value_specs: List[PivotValue],
    layout: str,
    sorting: Optional[Dict[str, str]] = None,
    show_subtotals: bool = False,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    if not group_rows and not group_columns:
        row = {
            _value_label(spec): _json_safe(_aggregate_series(df[spec.field], spec.aggregation))
            for spec in value_specs
        }
        row["__rowFields"] = {}
        return [row], _visible_columns([], value_specs, [])

    # Estimate pivot result size
    unique_rows = df[group_rows].drop_duplicates().shape[0] if group_rows else 1
    unique_cols = df[group_columns].drop_duplicates().shape[0] if group_columns else 1
    estimated_cells = unique_rows * unique_cols * len(value_specs)
    if estimated_cells > 1000000:  # 1 million cells limit
        raise PivotError(
            f"Pivot would generate approximately {estimated_cells:,} cells, which exceeds the limit of 1,000,000. "
            f"Please select fewer grouping fields or apply filters to reduce the dataset size. "
            f"(Current: {unique_rows} unique row groups × {unique_cols} unique column groups × {len(value_specs)} value fields)"
        )

    row_cols = [_display_group_name(f, grouped_labels) for f in group_rows]
    leaf = _pivot_frame(df, group_rows, group_columns, value_specs, grouped_labels)
    value_columns = [c for c in leaf.columns if c not in row_cols]

    # True row total across column groups (only meaningful with exactly
    # one value spec). It is re-aggregated from the source rows, so an
    # average row total is the average of the records, not the sum of
    # per-column averages.
    has_row_total = bool(group_columns) and len(value_specs) == 1 and len(value_columns) > 1
    if has_row_total:
        leaf = _attach_row_total(leaf, df, group_rows, row_cols, value_specs, grouped_labels)

    # Sort hierarchically: every row field takes part (in field order) so
    # groups stay contiguous; the user's direction applies where given.
    if row_cols:
        directions = {
            _display_group_name(_group_field_name(raw, grouped_labels), grouped_labels): (d or "asc").lower()
            for raw, d in (sorting or {}).items()
        }
        if directions:
            leaf = leaf.sort_values(
                by=row_cols,
                ascending=[directions.get(c, "asc") not in {"desc", "descending"} for c in row_cols],
                key=_sort_key,
                kind="mergesort",
            ).reset_index(drop=True)

    rows = _df_to_records(leaf)
    for r in rows:
        r["__rowFields"] = {c: r.get(c) for c in row_cols}

    if show_subtotals and len(group_rows) >= 2:
        rows = _with_subtotal_rows(
            rows, df, group_rows, group_columns, row_cols, value_specs, grouped_labels, has_row_total,
        )

    # Limit number of rows in result. Capture the original count BEFORE
    # truncation so the warning message is accurate.
    original_row_count = len(rows)
    if original_row_count > MAX_PIVOT_RESULT_ROWS:
        rows = rows[:MAX_PIVOT_RESULT_ROWS]
        rows.insert(0, {
            "_warning": (
                f"Result truncated to first {MAX_PIVOT_RESULT_ROWS:,} of "
                f"{original_row_count:,} rows due to size limits. "
                f"Apply filters or reduce grouping fields to see all rows."
            )
        })

    compact = layout == "compact" and len(group_rows) > 1
    _annotate_hierarchy(rows, row_cols)
    if compact:
        for row in rows:
            if "_warning" in row:
                continue
            if row.get("__isSubtotal"):
                prefix = [str(row["__rowFields"].get(c)) for c in row_cols[:-1]]
                row["Rows"] = " / ".join(prefix) + " Total"
            else:
                row["Rows"] = " / ".join(str(row.get(label, "")) for label in row_cols)
            for label in row_cols:
                row.pop(label, None)
        first_cols = ["Rows"]
    else:
        first_cols = row_cols

    return rows, _visible_columns(first_cols, value_specs, value_columns)


def _attach_row_total(
    frame: pd.DataFrame,
    df: pd.DataFrame,
    group_rows: List[str],
    row_cols: List[str],
    value_specs: List[PivotValue],
    grouped_labels: Dict[str, str],
) -> pd.DataFrame:
    totals = _pivot_frame(df, group_rows, [], value_specs, grouped_labels)
    label = _value_label(value_specs[0])
    totals = totals.rename(columns={label: "row_total"})
    if not row_cols:
        frame = frame.copy()
        frame["row_total"] = totals["row_total"].iloc[0] if len(totals) else None
        return frame
    return frame.merge(totals[row_cols + ["row_total"]], on=row_cols, how="left")


def _annotate_hierarchy(rows: List[Dict[str, Any]], row_cols: List[str]) -> None:
    """Stamp every row with `__level` / `__parentKey` (and `__groupKey` on
    subtotal rows) from its `__rowFields`, identically in both layouts.

    Regular rows sit at the deepest level; their parent key is the
    "||"-joined values of every row field above it. A subtotal row sits
    one level up and its `__groupKey` equals the `__parentKey` of the
    rows it summarises, which is what the grid's expand/collapse uses."""
    if not row_cols:
        return
    n = len(row_cols)
    for r in rows:
        if "_warning" in r or "__rowFields" not in r:
            continue
        vals = [str(r["__rowFields"].get(c, "")) for c in row_cols]
        if r.get("__isSubtotal"):
            r["__level"] = n - 2
            r["__parentKey"] = "||".join(vals[: n - 2])
            r["__groupKey"] = "||".join(vals[: n - 1])
        else:
            r["__level"] = n - 1
            r["__parentKey"] = "||".join(vals[: n - 1])


# ── Phase 7 — Subtotals ──────────────────────────────────────────────────

def _with_subtotal_rows(
    rows: List[Dict[str, Any]],
    df: pd.DataFrame,
    group_rows: List[str],
    group_columns: List[str],
    row_cols: List[str],
    value_specs: List[PivotValue],
    grouped_labels: Dict[str, str],
    has_row_total: bool,
) -> List[Dict[str, Any]]:
    """Insert a subtotal row after every group at the second-to-last
    row-field level (Excel behaviour).

    Subtotal values are aggregated from the source records of the group,
    so every aggregation (including average / min / max) and every column
    group is correct — they are not derived from the leaf values."""
    prefix_fields = group_rows[:-1]
    prefix_cols = row_cols[:-1]
    sub = _pivot_frame(df, prefix_fields, group_columns, value_specs, grouped_labels)
    if has_row_total:
        sub = _attach_row_total(sub, df, prefix_fields, prefix_cols, value_specs, grouped_labels)
    by_prefix = {
        tuple(rec.get(c) for c in prefix_cols): rec
        for rec in _df_to_records(sub)
    }

    def subtotal_for(prefix: Tuple[Any, ...]) -> Dict[str, Any]:
        rec = dict(by_prefix.get(prefix, {}))
        for c in row_cols:
            rec[c] = rec.get(c, "") if c in prefix_cols else ""
        rec["__rowFields"] = {c: v for c, v in zip(prefix_cols, prefix)}
        rec["__isSubtotal"] = True
        return rec

    out: List[Dict[str, Any]] = []
    current: Optional[Tuple[Any, ...]] = None
    for r in rows:
        prefix = tuple(r.get(c) for c in prefix_cols)
        if current is not None and prefix != current:
            out.append(subtotal_for(current))
        current = prefix
        out.append(r)
    if current is not None:
        out.append(subtotal_for(current))
    return out


# ── Phase 7 — Repeat item labels (Tabular Form) ─────────────────────────

def _apply_repeat_item_labels(
    rows: List[Dict[str, Any]],
    row_cols: List[str],
) -> None:
    """Fill blank grouped cells with the value from the row above,
    exactly like Excel's Tabular Form. The deepest field of a subtotal
    row stays blank (a subtotal has no leaf value)."""
    if not row_cols:
        return
    n = len(row_cols)
    last_values: List[Any] = [None] * n
    for r in rows:
        if "_warning" in r or r.get("__isGrandTotal") or r.get("__isColumnTotal"):
            continue
        is_subtotal = bool(r.get("__isSubtotal"))
        for i, field in enumerate(row_cols):
            v = r.get(field)
            if v is None or v == "":
                if is_subtotal and i == n - 1:
                    continue
                r[field] = last_values[i]
            else:
                last_values[i] = v


# ── Phase 7 — Column totals ─────────────────────────────────────────────

def _insert_column_total_row(
    rows: List[Dict[str, Any]],
    filtered_df: pd.DataFrame,
    group_rows: List[str],
    group_columns: List[str],
    grouped_labels: Dict[str, str],
    value_specs: List[PivotValue],
    pivot_columns: List[str],
    layout: str,
) -> None:
    """Append a per-column-total row (aggregated from every filtered
    record, per column group). Marked `__isColumnTotal` so the grid pins
    it beneath the grand total."""
    if not value_specs:
        return
    totals = _pivot_frame(filtered_df, [], group_columns, value_specs, grouped_labels)
    new_row: Dict[str, Any] = _df_to_records(totals)[0] if len(totals) else {}
    if "row_total" in pivot_columns and len(value_specs) == 1:
        new_row["row_total"] = _json_safe(
            _aggregate_series(filtered_df[value_specs[0].field], value_specs[0].aggregation)
        )
    new_row["__isColumnTotal"] = True

    label_text = "Column Total"
    if layout == "compact" and len(group_rows) > 1:
        new_row["Rows"] = label_text
    else:
        row_cols = [_display_group_name(f, grouped_labels) for f in group_rows]
        for i, field in enumerate(row_cols):
            new_row[field] = label_text if i == 0 else ""
    rows.append(new_row)


def _compute_totals(
    df: pd.DataFrame,
    value_specs: List[PivotValue],
    rows: List[Dict[str, Any]],
    totals_opts: TotalsOptions,
) -> Dict[str, Any]:
    """
    Compute grand totals and honour the `show_grand_totals` /
    `show_row_totals` toggles. Row totals themselves are computed by the
    engine from the source records (see `_attach_row_total`).
    """
    grand: Dict[str, Any] = {}
    if totals_opts.show_grand_totals:
        for spec in value_specs:
            grand[_value_label(spec)] = _json_safe(_aggregate_series(df[spec.field], spec.aggregation))
    else:
        # Still expose the keys so the frontend can detect that totals were disabled
        for spec in value_specs:
            grand[_value_label(spec)] = None

    if not totals_opts.show_row_totals:
        for row in rows:
            row.pop("row_total", None)

    return {"grand": grand, "row_total_field": "row_total"}


def _selection_series(series: pd.Series) -> pd.Series:
    """Return a string Series suitable for selection matching.

    Datetime cells are formatted as ISO-8601 (e.g. "2026-06-29T00:00:00")
    to match the ISO strings the pivot layer serialises via
    ``.isoformat()`` — pandas' own ``.astype(str)`` produces
    "2026-06-29 00:00:00" (space separator) and the two never matched,
    so drilldown / soft-delete / email returned zero rows for
    ungrouped datetime fields.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.map(lambda v: v.isoformat() if pd.notna(v) else None).astype(str)
    return series.astype(str)


def _selection_mask(series: pd.Series, expected: Any) -> pd.Series:
    """Boolean mask of the cells in `series` that equal one pivot-row value.

    - None / "(blank)" match empty cells (the pivot shows nulls as
      "(blank)"), plus any literal "(blank)" text, which the pivot merges
      into the same group.
    - Numbers are compared numerically, so a float column value `2024.0`
      matches the `2024` that JSON round-tripping produces.
    - Everything else is compared as text (datetimes as ISO-8601).
    """
    if expected is None or expected == NULL_PLACEHOLDER:
        mask = series.isna()
        if series.dtype == object:
            mask = mask | (series.astype(str) == NULL_PLACEHOLDER)
        return mask
    if (
        isinstance(expected, (int, float))
        and not isinstance(expected, bool)
        and pd.api.types.is_numeric_dtype(series)
        and not pd.api.types.is_bool_dtype(series)
    ):
        return series == expected
    return _selection_series(series) == str(expected)


def _apply_selection(
    df: pd.DataFrame,
    selection: Dict[str, Any],
    grouped_labels: Dict[str, str],
    *,
    allow_empty: bool = False,
) -> pd.DataFrame:
    """Return the rows of `df` matching every {field: value} in `selection`.

    Safety rules (this feeds Delete Records):
      - an empty selection matches NOTHING unless `allow_empty` is set
        (only true when the pivot has no row fields, i.e. its single row
        legitimately represents every filtered record);
      - an unknown field raises instead of being skipped, because
        skipping a criterion silently widens the match.
    """
    if not selection:
        return df if allow_empty else df.iloc[0:0]
    matched = df
    for field, expected in selection.items():
        match_field = _selection_field_name(field, grouped_labels)
        if match_field not in matched.columns:
            raise PivotError(f"Selection field not found: {field}")
        matched = matched[_selection_mask(matched[match_field], expected)]
    return matched


def _date_group_series(series: pd.Series, grouping: str) -> pd.Series:
    """Convert datetime series to grouped string representation."""
    # Convert to datetime, coercing errors to NaT
    dt = pd.to_datetime(series, errors="coerce")

    if grouping == "year":
        result = dt.dt.year.astype("Int64").astype(str)
    elif grouping == "quarter":
        year = dt.dt.year.astype("Int64").astype(str)
        quarter = dt.dt.quarter.astype("Int64").astype(str)
        result = year + "-Q" + quarter
    elif grouping == "month":
        # Use period for month grouping
        result = dt.dt.to_period("M").astype(str)
    elif grouping == "week":
        iso = dt.dt.isocalendar()
        year = iso.year.astype(str)
        week = iso.week.astype(str).str.zfill(2)
        result = year + "-W" + week
    else:  # day
        result = dt.dt.strftime("%Y-%m-%d")

    # Replace NaT with None for consistency
    return result.where(dt.notna(), None)


def _date_group_field(field: str, grouping: str) -> str:
    return f"__pivot_{field}_{grouping}"


def _group_field_name(field: str, grouped_labels: Dict[str, str]) -> str:
    return grouped_labels.get(field, field)


def _display_group_name(field: str, grouped_labels: Dict[str, str]) -> str:
    for original, grouped in grouped_labels.items():
        if field == grouped:
            return f"{original}_{grouped.rsplit('_', 1)[-1]}"
    return field


def _rename_group_columns(df: pd.DataFrame, grouped_labels: Dict[str, str]) -> pd.DataFrame:
    rename_map = {
        grouped: _display_group_name(grouped, grouped_labels)
        for grouped in grouped_labels.values()
        if grouped in df.columns
    }
    return df.rename(columns=rename_map)


def _visible_columns(
    group_columns: List[str], value_specs: List[PivotValue], pivot_value_columns: List[str]
) -> List[str]:
    if pivot_value_columns:
        columns = group_columns + pivot_value_columns
        if len(value_specs) == 1 and len(pivot_value_columns) > 1:
            columns.append("row_total")
        return columns
    return group_columns + [_value_label(spec) for spec in value_specs]


def _display_row_columns(
    group_rows: List[str], grouped_labels: Dict[str, str], layout: str
) -> List[str]:
    if layout == "compact" and len(group_rows) > 1:
        return ["Rows"]
    return [_display_group_name(field, grouped_labels) for field in group_rows]


def _selection_field_name(field: str, grouped_labels: Dict[str, str]) -> str:
    for original, grouped in grouped_labels.items():
        if field in {original, grouped, _display_group_name(grouped, grouped_labels)}:
            return grouped
    return field


def _value_label(spec: PivotValue) -> str:
    return spec.label or f"{spec.aggregation}_{spec.field}"


def _aggregate_series(series: pd.Series, aggregation: str) -> Any:
    if aggregation == "count":
        return int(series.count())
    if aggregation == "sum":
        return pd.to_numeric(series, errors="coerce").sum()
    if aggregation == "average":
        return pd.to_numeric(series, errors="coerce").mean()
    if aggregation == "min":
        return series.min()
    return series.max()


def _coerce_comparison_value(series: pd.Series, value: Any) -> Any:
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(value)
    return value


def _df_to_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    visible_df = df[[c for c in df.columns if not str(c).startswith("__pivot_")]].copy()
    visible_df = visible_df.where(pd.notnull(visible_df), other=None)
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in visible_df.to_dict(orient="records")
    ]


def _json_safe(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value
