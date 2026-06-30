"""
Phase 3 pivot engine.

The backend is the authoritative pivot calculator. The frontend should send a
pivot definition and render this service's output without recalculating it.

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

    value_columns = [c for c in pivot_df.columns if c not in [_display_group_name(f, grouped_labels) for f in group_rows]]
    return rows, _visible_columns(first_cols, value_specs, value_columns)


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
                and key not in {"row_total", "_warning", "Rows"}
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
