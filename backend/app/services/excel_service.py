"""
Excel / CSV parsing service.

Responsibilities:
- Read uploaded files with pandas
- Extract sheet names, row counts, column names
- Infer column datatypes (string | integer | float | boolean | datetime)
- Return a preview of the first N rows
"""

from pathlib import Path
from typing import List, Dict, Any

import pandas as pd

from app.config.settings import PREVIEW_ROW_LIMIT, MAX_ROWS_ALLOWED, MAX_COLUMNS_ALLOWED
from app.schemas.dataset import SheetMeta, ColumnInfo


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_metadata(filepath: str) -> Dict[str, Any]:
    """
    Parse an Excel (.xlsx) or CSV file and return:
      - sheets      : list[SheetMeta]
      - total_rows  : int  (rows in the first / only sheet)
      - total_cols  : int  (columns in the first / only sheet)
      - preview     : list[dict]  (first PREVIEW_ROW_LIMIT rows, JSON-safe)
      - sheet_columns : dict[sheet_name -> list[ColumnInfo]]  (Phase 2)

    Raises ValueError if the file is empty, has no sheets, or exceeds size limits.
    """
    ext = Path(filepath).suffix.lower()

    if ext == ".csv":
        return _parse_csv(filepath)
    elif ext == ".xlsx":
        return _parse_excel(filepath)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def load_sheet_df(filepath: str, sheet_name: str) -> pd.DataFrame:
    """
    Load a single sheet / CSV into a DataFrame (used by dataset_service for
    on-demand preview and column queries without re-parsing everything).
    """
    ext = Path(filepath).suffix.lower()
    if ext == ".csv":
        return pd.read_csv(filepath)
    return pd.read_excel(filepath, sheet_name=sheet_name, engine="openpyxl")


# ---------------------------------------------------------------------------
# Datatype inference
# ---------------------------------------------------------------------------

def infer_column_info(df: pd.DataFrame) -> List[ColumnInfo]:
    """
    Analyse every column in *df* and return a ColumnInfo list with:
      - column_name
      - data_type  : string | integer | float | boolean | datetime
      - is_nullable: True if any NaN / NaT / None found
    """
    result: List[ColumnInfo] = []
    for col in df.columns:
        series = df[col]
        is_nullable = bool(series.isna().any())
        data_type   = _infer_dtype(series)
        result.append(
            ColumnInfo(
                column_name=str(col),
                data_type=data_type,
                is_nullable=is_nullable,
            )
        )
    return result


def _infer_dtype(series: pd.Series) -> str:
    """Map a pandas Series to one of: string | integer | float | boolean | datetime."""
    # Drop nulls for inference
    non_null = series.dropna()

    if non_null.empty:
        return "string"

    # Already typed by pandas
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"

    # For object / mixed columns, decide based on observed non-null values.
    # This covers cases like [True, False, None] where pandas keeps dtype=object
    # (boolean) but the result of `pd.to_numeric` would be float due to NaN.
    sample = non_null.head(50)
    py_types = set(type(v).__name__ for v in sample)

    # If every non-null value is a Python bool → boolean
    if py_types == {"bool"}:
        return "boolean"

    # Float column check (must come after the bool check above to avoid
    # misclassifying bool/float mixed columns)
    if pd.api.types.is_float_dtype(series):
        # Heuristic: a float column whose non-null values are *all* exactly
        # 0.0 or 1.0 is most likely a boolean column that lost its type
        # through an Excel / openpyxl roundtrip. Surface it as boolean
        # so the UI can offer the correct aggregations.
        try:
            uniq = set(non_null.unique().tolist())
            if uniq and uniq.issubset({0.0, 1.0, 0, 1}):
                return "boolean"
        except Exception:
            pass
        return "float"

    # For object columns: try coercing to numeric / datetime
    if series.dtype == object:
        # Try datetime (strict parsing; no deprecation warnings)
        try:
            converted = pd.to_datetime(non_null, errors="raise")
            if converted.notna().all():
                return "datetime"
        except Exception:
            pass

        # Try boolean (yes/no/true/false) before numeric because
        # `pd.to_numeric("true")` would raise and fall through cleanly.
        lower_vals = non_null.astype(str).str.strip().str.lower().unique()
        if set(lower_vals).issubset({"true", "false", "yes", "no", "1", "0"}):
            return "boolean"

        # Try numeric
        try:
            numeric = pd.to_numeric(non_null, errors="raise")
            if pd.api.types.is_integer_dtype(numeric):
                return "integer"
            return "float"
        except Exception:
            pass

    return "string"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_excel(filepath: str) -> Dict[str, Any]:
    xl = pd.ExcelFile(filepath, engine="openpyxl")
    sheet_names = xl.sheet_names

    if not sheet_names:
        raise ValueError(
            "The uploaded Excel file is empty. Please upload a workbook that contains "
            "at least one sheet with data."
        )

    sheets: List[SheetMeta] = []
    sheet_columns: Dict[str, List[ColumnInfo]] = {}
    sheet_dataframes: Dict[str, pd.DataFrame] = {}

    for sheet_name in sheet_names:
        # Read up to MAX_ROWS_ALLOWED + 1 rows so we can detect overflow accurately.
        df = xl.parse(sheet_name, nrows=MAX_ROWS_ALLOWED + 1)
        df.columns = df.columns.astype(str)

        # Validate size limits (cap on first MAX_ROWS_ALLOWED rows)
        if len(df) > MAX_ROWS_ALLOWED:
            raise ValueError(
                f"Sheet '{sheet_name}' has more than {MAX_ROWS_ALLOWED:,} rows, which "
                "exceeds the maximum allowed. Please reduce the dataset size or use data sampling."
            )
        if len(df.columns) > MAX_COLUMNS_ALLOWED:
            raise ValueError(
                f"Sheet '{sheet_name}' has {len(df.columns):,} columns, which exceeds the "
                f"maximum allowed ({MAX_COLUMNS_ALLOWED:,}). Please reduce the number of columns."
            )

        # Friendly error: sheet exists but is fully empty (no rows at all)
        if len(df) == 0:
            raise ValueError(
                f"Sheet '{sheet_name}' is empty. Please upload a workbook where every sheet "
                "contains at least one row of data."
            )

        sheets.append(
            SheetMeta(
                sheet_name=sheet_name,
                row_count=len(df),
                column_names=list(df.columns),
            )
        )
        sheet_columns[sheet_name] = infer_column_info(df)
        sheet_dataframes[sheet_name] = df

    # Reuse the first sheet we already parsed (avoids re-opening the file)
    first_df = sheet_dataframes[sheet_names[0]]
    preview = _df_to_preview(first_df)

    return {
        "sheets":        sheets,
        "total_rows":    len(first_df),
        "total_cols":    len(first_df.columns),
        "preview":       preview,
        "sheet_columns": sheet_columns,
    }


def _parse_csv(filepath: str) -> Dict[str, Any]:
    try:
        df = pd.read_csv(filepath, nrows=MAX_ROWS_ALLOWED + 1)
    except pd.errors.EmptyDataError as exc:
        raise ValueError(
            "The uploaded CSV file is empty. Please upload a file that contains at least "
            "one header row and one data row."
        ) from exc
    except Exception as exc:
        raise ValueError(f"Could not read CSV file: {exc}") from exc

    df.columns = df.columns.astype(str)

    if len(df) == 0:
        raise ValueError(
            "The uploaded CSV file is empty. Please upload a file that contains at least "
            "one header row and one data row."
        )

    # Validate size limits
    if len(df) > MAX_ROWS_ALLOWED:
        raise ValueError(
            f"CSV has more than {MAX_ROWS_ALLOWED:,} rows, which exceeds the maximum "
            "allowed. Please reduce the dataset size or use data sampling."
        )
    if len(df.columns) > MAX_COLUMNS_ALLOWED:
        raise ValueError(
            f"CSV has {len(df.columns):,} columns, which exceeds the maximum allowed "
            f"({MAX_COLUMNS_ALLOWED:,}). Please reduce the number of columns."
        )

    sheet = SheetMeta(
        sheet_name="Sheet1",
        row_count=len(df),
        column_names=list(df.columns),
    )
    preview = _df_to_preview(df)

    return {
        "sheets":        [sheet],
        "total_rows":    len(df),
        "total_cols":    len(df.columns),
        "preview":       preview,
        "sheet_columns": {"Sheet1": infer_column_info(df)},
    }


def _df_to_preview(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Convert the first PREVIEW_ROW_LIMIT rows to a JSON-safe list of dicts."""
    preview_df = df.head(PREVIEW_ROW_LIMIT).copy()

    # Replace NaN / NaT / Inf with None so JSON serialisation never fails
    preview_df = preview_df.where(pd.notnull(preview_df), other=None)

    # Stringify datetime columns so JSON doesn't choke
    for col in preview_df.columns:
        if pd.api.types.is_datetime64_any_dtype(preview_df[col]):
            preview_df[col] = preview_df[col].astype(str)

    preview_df.columns = preview_df.columns.astype(str)
    return preview_df.to_dict(orient="records")
