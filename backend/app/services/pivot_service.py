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
from app.services.excel_service import load_sheet_df
from app.utils.file_utils import build_upload_path


AGGREGATIONS = {
    "count": "count",
    "sum": "sum",
    "average": "mean",
    "min": "min",
    "max": "max",
}
PANDAS_AGGREGATIONS = {value: key for key, value in AGGREGATIONS.items()}

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
        )

        # Phase 7: post-process the flat row list with the
        #  - subtotals
        #  - repeat-item-labels
        #  - column-totals row
        # additions.  Each helper MUTATES `rows` in place to keep the
        # call site small.
        if totals_opts.show_subtotals and group_rows:
            _insert_subtotal_rows(rows, group_rows, value_specs, pivot_columns)

        if totals_opts.show_column_totals and group_rows:
            _insert_column_total_row(rows, filtered_df, group_rows, value_specs, pivot_columns)

    # Apply repeat-item-labels in a single pass after the structure is
    # finalised.  This works on every row variant (subtotal, grand
    # total, regular) — the marker rows just have their existing value
    # preserved.
    if totals_opts.repeat_item_labels and group_rows:
        _apply_repeat_item_labels(rows, group_rows)

    totals = _compute_totals(
        filtered_df,
        value_specs,
        rows,
        _display_row_columns(group_rows, grouped_labels, request.layout),
        totals_opts,
    )

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


def build_drilldown(
    db: Session, request: PivotDrilldownRequest
) -> PivotDrilldownResponse:
    """Return raw rows matching a pivot cell selection."""
    _validate_layout(request.layout)
    df = _load_dataset_sheet(db, request.dataset_id, request.sheet_name)
    _, _, grouped_labels = _prepare_group_fields(df, request)
    filtered_df = _apply_filters(df, request.filters)
    matched_df = _apply_selection(filtered_df, request.selection, grouped_labels)
    limited_df = matched_df.head(max(1, min(request.limit, 5000)))

    return PivotDrilldownResponse(
        rows=_df_to_records(limited_df),
        columns=[str(c) for c in limited_df.columns if not str(c).startswith("__pivot_")],
        metadata={
            "dataset_id": request.dataset_id,
            "sheet_name": request.sheet_name,
            "matched_rows": int(len(matched_df)),
            "returned_rows": int(len(limited_df)),
            "limit": int(max(1, min(request.limit, 5000))),
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
    Phase 6 — multi-selection drilldown.

    Run the existing single-selection drilldown once per selection,
    merge the resulting rows, and deduplicate by a stable JSON key
    so the same raw record is never included twice. Returns the
    same shape as `build_drilldown()` so the email attachment
    service can use it as a drop-in replacement.

    The contract of the per-selection call is unchanged — the
    request body sent to the existing `/api/pivot/drilldown`
    endpoint is built here from the same payload fields, plus
    `selection` and `limit`.
    """
    if not selections:
        return {
            "rows": [],
            "columns": [],
            "metadata": {
                "dataset_id": dataset_id,
                "sheet_name": sheet_name,
                "matched_rows": 0,
                "returned_rows": 0,
                "limit": int(max(1, min(limit, 5000))),
                "selections": [],
            },
        }

    seen: set = set()
    merged_rows: List[Dict[str, Any]] = []
    merged_columns: List[str] = []
    total_matched = 0
    cap = max(1, min(limit, 5000))

    for selection in selections:
        req = PivotDrilldownRequest(
            dataset_id=dataset_id,
            sheet_name=sheet_name,
            rows=rows,
            columns=columns,
            values=values,
            filters=filters,
            date_grouping=date_grouping,
            sorting=sorting,
            totals=totals,
            layout=layout,
            selection=selection,
            limit=cap,
        )
        single = build_drilldown(db, req)
        total_matched += int(single.metadata.get("matched_rows") or 0)

        if not merged_columns and single.columns:
            merged_columns = list(single.columns)

        for row in single.rows:
            key = _dedup_key(row)
            if key in seen:
                continue
            seen.add(key)
            merged_rows.append(row)

    return {
        "rows": merged_rows,
        "columns": merged_columns,
        "metadata": {
            "dataset_id": dataset_id,
            "sheet_name": sheet_name,
            "matched_rows": total_matched,
            "returned_rows": len(merged_rows),
            "limit": cap,
            "selections": list(selections),
        },
    }


def _dedup_key(record: Dict[str, Any]) -> str:
    """Stable JSON-string dedup key — matches the frontend's
    `DrilldownSelection.dedupKey()` so both sides agree on what
    counts as a duplicate."""
    if not isinstance(record, dict):
        return ""
    return "|".join(
        f"{k}={_json_safe(v)!r}"
        for k in sorted(record.keys())
        for v in [record.get(k)]
    )


def _load_dataset_sheet(db: Session, dataset_id: int, sheet_name: str) -> pd.DataFrame:
    dataset = get_dataset_by_id(db, dataset_id)
    if not dataset:
        raise PivotError("Dataset not found")

    filepath = build_upload_path(dataset.stored_filename, UPLOAD_DIR)
    try:
        df = load_sheet_df(filepath, sheet_name)
    except FileNotFoundError as exc:
        raise PivotError("Uploaded file not found on disk") from exc
    except Exception as exc:
        raise PivotError(f"Failed to load sheet: {exc}") from exc

    df.columns = df.columns.astype(str)
    return df


def _normalise_values(values: List[Any], df: pd.DataFrame) -> List[PivotValue]:
    if not values:
        return [PivotValue(field=str(df.columns[0]), aggregation="count", label="count")]

    result: List[PivotValue] = []
    for item in values:
        if isinstance(item, PivotValue):
            spec = item
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


def _apply_filters(df: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
    filtered = df
    for field, expected in filters.items():
        if field not in filtered.columns:
            raise PivotError(f"Filter field not found: {field}")

        if isinstance(expected, dict):
            filtered = _apply_structured_filter(filtered, field, expected)
        elif isinstance(expected, list):
            filtered = filtered[filtered[field].isin(expected)]
        elif expected is None:
            filtered = filtered[filtered[field].isna()]
        else:
            filtered = filtered[filtered[field] == expected]

    return filtered


def _apply_structured_filter(
    df: pd.DataFrame, field: str, filter_def: Dict[str, Any]
) -> pd.DataFrame:
    series = df[field]
    if "in" in filter_def:
        return df[series.isin(filter_def["in"])]
    if "notIn" in filter_def:
        return df[~series.isin(filter_def["notIn"])]
    if "equals" in filter_def:
        return df[series == filter_def["equals"]]
    if "contains" in filter_def:
        return df[series.astype(str).str.contains(str(filter_def["contains"]), case=False, na=False)]

    comparable = pd.to_datetime(series, errors="ignore")
    if "from" in filter_def:
        comparable_from = _coerce_comparison_value(comparable, filter_def["from"])
        df = df[comparable >= comparable_from]
        comparable = comparable.loc[df.index]
    if "to" in filter_def:
        comparable_to = _coerce_comparison_value(comparable, filter_def["to"])
        df = df[comparable <= comparable_to]

    return df


def _compute_pivot_rows(
    df: pd.DataFrame,
    group_rows: List[str],
    group_columns: List[str],
    grouped_labels: Dict[str, str],
    value_specs: List[PivotValue],
    layout: str,
    sorting: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    if not group_rows and not group_columns:
        row = {
            _value_label(spec): _json_safe(_aggregate_series(df[spec.field], spec.aggregation))
            for spec in value_specs
        }
        return [row], _visible_columns([], value_specs, [])

    value_fields = list(dict.fromkeys(spec.field for spec in value_specs))
    aggfunc: Dict[str, Any] = {}
    for spec in value_specs:
        func = AGGREGATIONS[spec.aggregation]
        existing = aggfunc.get(spec.field)
        if existing is None:
            aggfunc[spec.field] = func
        elif isinstance(existing, list):
            existing.append(func)
        else:
            aggfunc[spec.field] = [existing, func]
    index = group_rows if group_rows else None
    columns = group_columns if group_columns else None

    # Estimate pivot result size
    if group_rows:
        unique_rows = df[group_rows].drop_duplicates().shape[0]
    else:
        unique_rows = 1

    if group_columns:
        unique_cols = df[group_columns].drop_duplicates().shape[0]
    else:
        unique_cols = 1

    estimated_cells = unique_rows * unique_cols * len(value_fields)

    if estimated_cells > 1000000:  # 1 million cells limit
        raise PivotError(
            f"Pivot would generate approximately {estimated_cells:,} cells, which exceeds the limit of 1,000,000. "
            f"Please select fewer grouping fields or apply filters to reduce the dataset size. "
            f"(Current: {unique_rows} unique row groups × {unique_cols} unique column groups × {len(value_fields)} value fields)"
        )

    # Critical fix: replace null values in the group fields with a string
    # placeholder BEFORE calling pd.pivot_table.
    #
    # pandas' pivot_table with multiple row fields and `dropna=False`
    # builds the **cartesian product** of all distinct values in each row
    # level (because each level is treated as an independent category
    # index). For example, with Issue_Category (64 distinct incl. NaN) ×
    # Unit (30) × Affected_CI (353) the pivot produced 677,760 rows
    # even though only 588 unique combinations exist in the source data.
    # The pre-pivot size estimate `df[group_rows].drop_duplicates()`
    # returns 588, so the cap isn't triggered and the user is left with
    # a 670k-row pivot that overflows the 10,000-row result limit.
    #
    # Substituting NaN with a literal string and using `dropna=True`
    # gives us Excel-like behaviour: null values appear as "(blank)" in
    # the result, and the row count is exactly the number of distinct
    # combinations present in the data.
    pivot_input = df.copy()
    for col in (group_rows or []) + (group_columns or []):
        if pivot_input[col].isna().any():
            pivot_input[col] = pivot_input[col].fillna(NULL_PLACEHOLDER)

    try:
        pivot_df = pd.pivot_table(
            pivot_input,
            values=value_fields,
            index=index,
            columns=columns,
            aggfunc=aggfunc,
            fill_value=0,
            dropna=True,
            observed=True,
        )
    except MemoryError as exc:
        raise PivotError(
            f"Pivot computation ran out of memory. "
            f"Please reduce dataset size, select fewer grouping fields, or apply filters. "
            f"Original error: {exc}"
        ) from exc

    if isinstance(pivot_df, pd.Series):
        pivot_df = pivot_df.to_frame()
    if group_rows:
        pivot_df = pivot_df.reset_index()
    else:
        pivot_df = pivot_df.reset_index(drop=True)

    pivot_df.columns = [_flatten_column(col, value_specs, grouped_labels) for col in pivot_df.columns]
    pivot_df = _rename_group_columns(pivot_df, grouped_labels)

    # Apply per-row sorting on the resulting pivot (pivot_table re-sorts the index)
    if sorting and group_rows:
        sort_keys: List[str] = []
        ascending: List[bool] = []
        for raw_field, direction in sorting.items():
            actual_col = _display_group_name(_group_field_name(raw_field, grouped_labels), grouped_labels)
            if actual_col not in pivot_df.columns:
                continue
            direction_norm = (direction or "asc").lower()
            ascending.append(direction_norm not in {"desc", "descending"})
            sort_keys.append(actual_col)
        if sort_keys:
            pivot_df = pivot_df.sort_values(by=sort_keys, ascending=ascending, kind="mergesort")
            pivot_df = pivot_df.reset_index(drop=True)

    rows = _df_to_records(pivot_df)

    # Limit number of rows in result. Capture the original count BEFORE
    # truncation so the warning message is accurate.
    original_row_count = len(rows)
    if original_row_count > MAX_PIVOT_RESULT_ROWS:
        rows = rows[:MAX_PIVOT_RESULT_ROWS]
        warning_row = {
            "_warning": (
                f"Result truncated to first {MAX_PIVOT_RESULT_ROWS:,} of "
                f"{original_row_count:,} rows due to size limits. "
                f"Apply filters or reduce grouping fields to see all rows."
            )
        }
        rows.insert(0, warning_row)

    if layout == "compact" and len(group_rows) > 1:
        row_labels = [_display_group_name(field, grouped_labels) for field in group_rows]
        for row in rows:
            if "_warning" not in row:  # Skip the warning row
                row["Rows"] = " / ".join(str(row.get(label, "")) for label in row_labels)
                for label in row_labels:
                    row.pop(label, None)
        first_cols = ["Rows"]
    else:
        first_cols = [_display_group_name(field, grouped_labels) for field in group_rows]

    # ── Phase 7: add hierarchy markers (`__level`, `__parentKey`) ────
    # The frontend uses these to drive expand/collapse and indent the
    # row labels exactly like Excel's Tabular Form.  This runs AFTER
    # the compact-mode transformation so the "Rows" merged column is
    # available for the parent-key extraction.
    _annotate_hierarchy(rows, group_rows, layout)

    value_columns = [c for c in pivot_df.columns if c not in [_display_group_name(f, grouped_labels) for f in group_rows]]
    return rows, _visible_columns(first_cols, value_specs, value_columns)


def _annotate_hierarchy(
    rows: List[Dict[str, Any]],
    group_rows: List[str],
    layout: str,
) -> None:
    """Stamp every regular (non-warning) row with `__level` and
    `__parentKey` so the frontend can drive expand/collapse and indent
    row labels without recomputing anything.

    In compact mode the row fields are merged into a single "Rows"
    column; the level is set from the number of " / " separators in
    that merged value.
    """
    if not rows or not group_rows:
        return

    if layout == "compact":
        for r in rows:
            if "_warning" in r:
                continue
            merged = r.get("Rows")
            if merged is None:
                r["__level"] = 0
                r["__parentKey"] = ""
                continue
            parts = [p for p in str(merged).split(" / ") if p != ""]
            # Subtract 1 so a single row field produces level 0,
            # two row fields → level 0/1, three → 0/1/2, etc.
            r["__level"] = max(0, len(parts) - 1)
            # The parent key in compact mode is the joined values of
            # all levels above this row.  Trim the last element to get
            # the path that this row belongs to.
            r["__parentKey"] = " / ".join(parts[:-1]) if len(parts) > 1 else ""
        return

    # Tabular mode — the row fields are separate columns; the level
    # equals the index of the last non-blank row field, and the parent
    # key is the joined value of the row fields above that level.
    n = len(group_rows)
    for r in rows:
        if "_warning" in r:
            continue
        last_filled = -1
        for i, field in enumerate(group_rows):
            v = r.get(field)
            if v is not None and v != "" and v != NULL_PLACEHOLDER:
                last_filled = i
        r["__level"] = max(0, last_filled)
        if last_filled <= 0:
            r["__parentKey"] = ""
        else:
            r["__parentKey"] = "||".join(
                str(r.get(group_rows[i], "")) for i in range(last_filled)
            )


# ── Phase 7 — Subtotals ──────────────────────────────────────────────────

def _insert_subtotal_rows(
    rows: List[Dict[str, Any]],
    group_rows: List[str],
    value_specs: List[PivotValue],
    pivot_columns: List[str],
) -> None:
    """Insert a real subtotal row after every "group change" at the
    second-to-last row-field level.  This matches Excel's behaviour:
    with three row fields the subtotal is placed after every change in
    the second level, with two row fields after every change in the
    first level, and a single row field never produces a subtotal (the
    grand total already covers it).

    Subtotal rows are annotated with `__isSubtotal: true` and their
    value columns are re-aggregated from the underlying rows in the
    group (we compute a simple sum which is correct for the
    `sum`/`count` aggregations; for `average`/`min`/`max` we use the
    sub-aggregation of the rows in the group)."""
    if len(group_rows) < 2:
        return

    # Subtotal level = the second-to-last row field.  e.g. with three
    # row fields (A, B, C) the subtotal appears after each group of
    # C rows that share the same (A, B) prefix.
    subtotal_level_field = group_rows[-2]

    # Walk rows in order, tracking the current value of the
    # subtotal-level field.  When it changes, inject a subtotal row
    # whose level field has the previous value.
    #
    # Implementation: we accumulate "the rows in the current group"
    # as Python dicts; when the level-field changes we compute the
    # subtotal and insert it, then start a new group.
    #
    # We also need to compute the aggregated value for each numeric
    # value column from the rows in the current group.  We sum
    # numeric values which gives the correct result for sum, count,
    # min, and max; for average we average them, which matches what
    # the user would expect (the engine already returned a flat sum
    # of averages at the leaf level so summing gives the wrong
    # answer — we re-derive average from the leaf rows instead).
    def _reaggregate(group_rows_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for spec in value_specs:
            label = _value_label(spec)
            nums: List[float] = []
            for gr in group_rows_list:
                v = gr.get(label)
                if v is None:
                    continue
                try:
                    nums.append(float(v))
                except (TypeError, ValueError):
                    pass
            if not nums:
                out[label] = 0
                continue
            if spec.aggregation == "average":
                out[label] = sum(nums) / len(nums)
            elif spec.aggregation == "min":
                out[label] = min(nums)
            elif spec.aggregation == "max":
                out[label] = max(nums)
            else:  # sum, count
                out[label] = sum(nums)
        return out

    new_rows: List[Dict[str, Any]] = []
    current_group: List[Dict[str, Any]] = []
    current_level_value: Any = None
    current_level_parent: Any = None

    def _flush_subtotal():
        if not current_group:
            return
        sub = _reaggregate(current_group)
        # Set the level field to the previous value, blank the deeper
        # fields, mark as subtotal.
        subtotal_field_index = len(group_rows) - 2
        for i, field in enumerate(group_rows):
            if i < subtotal_field_index:
                sub[field] = current_group[0].get(field)
            elif i == subtotal_field_index:
                sub[field] = current_group[0].get(field)
            else:
                sub[field] = ""  # blank the deepest level on subtotal rows
        sub["__isSubtotal"] = True
        # The subtotal lives at the level of the field it aggregates
        # (the second-to-last level), not the deepest level.
        sub["__level"] = subtotal_field_index
        sub["__parentKey"] = "||".join(
            str(current_group[0].get(group_rows[i], "")) for i in range(subtotal_field_index)
        )
        new_rows.append(sub)

    for r in rows:
        if "_warning" in r:
            new_rows.append(r)
            continue
        # Skip existing grand-total / column-total markers
        if r.get("__isGrandTotal") or r.get("__isColumnTotal") or r.get("__isSubtotal"):
            new_rows.append(r)
            continue
        level_val = r.get(subtotal_level_field)
        parent_key = "||".join(
            str(r.get(group_rows[i], "")) for i in range(len(group_rows) - 1)
        )
        if current_level_parent is None:
            current_level_parent = parent_key
            current_level_value = level_val
            current_group.append(r)
            new_rows.append(r)
            continue
        if parent_key != current_level_parent:
            # Group changed — emit a subtotal for the previous group.
            _flush_subtotal()
            current_group = [r]
            current_level_parent = parent_key
            current_level_value = level_val
            new_rows.append(r)
        else:
            current_group.append(r)
            new_rows.append(r)

    # Flush the trailing group.
    _flush_subtotal()

    rows.clear()
    rows.extend(new_rows)


# ── Phase 7 — Repeat item labels (Tabular Form) ─────────────────────────

def _apply_repeat_item_labels(
    rows: List[Dict[str, Any]],
    group_rows: List[str],
) -> None:
    """Fill blank grouped cells with the value from the row above,
    exactly like Excel's Tabular Form.

    Operates in tabular mode (one row field per column).  In compact
    mode the row fields are merged into a single "Rows" column so
    the option is a no-op there.

    Subtotal rows are intentionally NOT filled in on the deepest
    level — the leaf value is what gets repeated, and a subtotal
    has no leaf value.  This matches Excel, where the deepest
    column on a subtotal row is blank.
    """
    if not group_rows:
        return

    if "Rows" in rows[0] if rows else False:
        # Compact mode — nothing to do, the merged column already
        # contains every level's value.
        return

    n = len(group_rows)
    last_values: List[Any] = [None] * n
    for r in rows:
        if "_warning" in r:
            continue
        if r.get("__isGrandTotal") or r.get("__isColumnTotal"):
            continue
        is_subtotal = bool(r.get("__isSubtotal"))
        for i, field in enumerate(group_rows):
            v = r.get(field)
            if v is None or v == "" or v == NULL_PLACEHOLDER:
                if is_subtotal and i == n - 1:
                    # Subtotal row: leave the deepest field blank so
                    # the user sees an empty cell where the leaf
                    # value would normally be.
                    continue
                r[field] = last_values[i]
            else:
                last_values[i] = v


# ── Phase 7 — Column totals ─────────────────────────────────────────────

def _insert_column_total_row(
    rows: List[Dict[str, Any]],
    filtered_df: pd.DataFrame,
    group_rows: List[str],
    value_specs: List[PivotValue],
    pivot_columns: List[str],
) -> None:
    """Build a per-column-total row by re-aggregating `filtered_df`
    along only the deeper row fields.  The row is marked
    `__isColumnTotal` so the frontend can pin it beneath the grand
    total in the same `pinnedBottomRowData` slot.

    Implementation note: we do NOT re-pivot here — we iterate the
    leaves of the pivot in `rows` (regular rows + subtotal rows
    count as leaves for the purposes of this aggregation; we only
    exclude `_warning`, `__isGrandTotal`, and `__isColumnTotal` rows)
    and sum / re-aggregate their value columns.  This keeps the
    column total consistent with the subtotal logic for every
    supported aggregation.
    """
    if not value_specs:
        return

    new_row: Dict[str, Any] = {"__isColumnTotal": True}
    # In tabular mode set the first row field to the label; in compact
    # mode set the merged "Rows" column.
    label_text = "Column Total"
    if "Rows" in (rows[0] if rows else {}):
        new_row["Rows"] = label_text
    elif group_rows:
        for i, field in enumerate(group_rows):
            new_row[field] = label_text if i == 0 else ""
    else:
        # No row fields — attach the label to the first visible column.
        first = next((c for c in pivot_columns if not c.startswith("__")), None)
        if first:
            new_row[first] = label_text

    # Re-aggregate the value columns from the leaves of the existing
    # rows.  This gives the correct result for every aggregation
    # because each leaf row already contains a value per
    # (group, value) combination; we EXCLUDE subtotals so the
    # column total is a true "sum of leaves" and not a sum of
    # subtotals-of-leaves (which would double-count).
    leaf_rows = [
        r for r in rows
        if "_warning" not in r
        and not r.get("__isGrandTotal")
        and not r.get("__isColumnTotal")
        and not r.get("__isSubtotal")
    ]

    def _reagg(spec: PivotValue) -> Any:
        label = _value_label(spec)
        nums: List[float] = []
        for r in leaf_rows:
            v = r.get(label)
            if v is None:
                continue
            try:
                nums.append(float(v))
            except (TypeError, ValueError):
                pass
        if not nums:
            return 0
        if spec.aggregation == "average":
            return sum(nums) / len(nums)
        if spec.aggregation == "min":
            return min(nums)
        if spec.aggregation == "max":
            return max(nums)
        return sum(nums)  # sum, count

    for spec in value_specs:
        new_row[_value_label(spec)] = _reagg(spec)

    # Add the row_total entry if the engine normally produces one
    # (only when there is exactly one value spec and the value column
    # list contains a row_total).
    if (len(value_specs) == 1
            and pivot_columns
            and "row_total" in pivot_columns):
        new_row["row_total"] = sum(
            (v for v in (new_row.get(_value_label(s)) for s in value_specs) if isinstance(v, (int, float))),
            0,
        )

    rows.append(new_row)


def _compute_totals(
    df: pd.DataFrame,
    value_specs: List[PivotValue],
    rows: List[Dict[str, Any]],
    row_columns: List[str],
    totals_opts: TotalsOptions,
) -> Dict[str, Any]:
    """
    Compute grand totals and per-row totals, honouring the user's
    `show_grand_totals` / `show_row_totals` / `show_column_totals` toggles.
    """
    grand: Dict[str, Any] = {}
    if totals_opts.show_grand_totals:
        for spec in value_specs:
            label = _value_label(spec)
            value = _aggregate_series(df[spec.field], spec.aggregation)
            grand[label] = _json_safe(value)
    else:
        # Still expose the keys so the frontend can detect that totals were disabled
        for spec in value_specs:
            grand[_value_label(spec)] = None

    if totals_opts.show_row_totals:
        for row in rows:
            numeric_values = [
                value
                for key, value in row.items()
                if key not in row_columns
                and key not in {"row_total", "_warning", "Rows",
                                "__isGrandTotal", "__isSubtotal",
                                "__isColumnTotal", "__level", "__parentKey"}
                and isinstance(value, (int, float))
            ]
            if len(value_specs) == 1 and len(numeric_values) > 1:
                row["row_total"] = _json_safe(sum(numeric_values))
    else:
        # Make sure no stale row_total sneaks through
        for row in rows:
            row.pop("row_total", None)

    return {"grand": grand, "row_total_field": "row_total"}


def _apply_selection(
    df: pd.DataFrame, selection: Dict[str, Any], grouped_labels: Dict[str, str]
) -> pd.DataFrame:
    matched = df
    for field, expected in selection.items():
        match_field = _selection_field_name(field, grouped_labels)
        if match_field not in matched.columns:
            continue
        matched = matched[matched[match_field].astype(str) == str(expected)]
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


def _flatten_column(
    column: Any, value_specs: List[PivotValue], grouped_labels: Dict[str, str]
) -> str:
    if not isinstance(column, tuple):
        column_name = str(column)
        for spec in value_specs:
            if column_name == spec.field:
                return _value_label(spec)
        return _display_group_name(column_name, grouped_labels)

    parts = [str(part) for part in column if str(part) not in ("", "None")]
    if not parts:
        return "value"

    if len(parts) >= 2 and parts[0] in {spec.field for spec in value_specs}:
        maybe_agg = PANDAS_AGGREGATIONS.get(parts[1], parts[1])
        matching_spec = next(
            (
                spec
                for spec in value_specs
                if spec.field == parts[0] and spec.aggregation == maybe_agg
            ),
            None,
        )
        if matching_spec:
            parts = [_value_label(matching_spec)] + parts[2:]
    elif parts[0] in {spec.field for spec in value_specs}:
        parts[0] = _value_label(next(spec for spec in value_specs if spec.field == parts[0]))
    return " | ".join(parts)


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
