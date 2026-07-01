"""
Pydantic schemas for Phase 3 pivot APIs.
"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class PivotValue(BaseModel):
    """One value field and aggregation used by the pivot engine."""

    field: str
    aggregation: str = "sum"
    label: Optional[str] = None


class TotalsOptions(BaseModel):
    """Toggles for grand / row / column totals and subtotals."""
    show_grand_totals: bool = Field(default=True, alias="showGrandTotals")
    show_row_totals: bool = Field(default=True, alias="showRowTotals")
    show_column_totals: bool = Field(default=False, alias="showColumnTotals")
    show_subtotals: bool = Field(default=False, alias="showSubtotals")
    # Phase 7 — Tabular Form: repeat the grouped value on every row
    # instead of leaving the second/third row field blank.
    repeat_item_labels: bool = Field(default=False, alias="repeatItemLabels")

    model_config = {"populate_by_name": True}


# ── Phase 7 — Display Options ──────────────────────────────────────────────
# The frontend can use these to drive column-level behaviour:
#   - numberFormat: format a numeric column as integer / decimal / currency /
#                   percentage / thousands separator
#   - dateFormat:   format a date column as yyyy-mm-dd / dd-mm-yyyy /
#                   MMM yyyy / MMMM yyyy / quarter / year
#   - conditionalFormats: highlight cells that match a rule
#                          (greater than / less than / equal / top 10 /
#                          bottom 10 / duplicate)
#   - frozenColumns: pin these columns to the left of the grid
#   - hiddenColumns: do not render these columns
#
# All fields default to no-op so existing clients (Phase 1-6) see no change
# in behaviour.
# ──────────────────────────────────────────────────────────────────────────

class ConditionalFormat(BaseModel):
    """A single conditional-formatting rule applied to one field."""
    field: str
    type: str  # gt | lt | eq | top10 | bottom10 | duplicates
    value: Optional[Union[int, float, str]] = None
    # "background" is a CSS colour string. Optional — the frontend applies a
    # sensible default if it is missing.
    background: Optional[str] = None

    model_config = {"populate_by_name": True}


class DisplayOptions(BaseModel):
    """Per-pivot display options. All keys are optional / default to no-op."""
    number_format: Dict[str, str] = Field(default_factory=dict, alias="numberFormat")
    date_format: Dict[str, str] = Field(default_factory=dict, alias="dateFormat")
    conditional_formats: List[ConditionalFormat] = Field(
        default_factory=list, alias="conditionalFormats"
    )
    frozen_columns: List[str] = Field(default_factory=list, alias="frozenColumns")
    hidden_columns: List[str] = Field(default_factory=list, alias="hiddenColumns")

    model_config = {"populate_by_name": True}


class PivotRequest(BaseModel):
    """Request contract for the pivot engine (used by compute + validate)."""

    dataset_id: int = Field(alias="datasetId")
    sheet_name: str = Field(alias="sheetName")
    rows: List[str] = Field(default_factory=list)
    columns: List[str] = Field(default_factory=list)
    values: List[Union[str, PivotValue]] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
    date_grouping: Dict[str, str] = Field(default_factory=dict, alias="dateGrouping")
    layout: str = "tabular"
    # Phase 3 additions
    sorting: Dict[str, str] = Field(default_factory=dict)
    totals: TotalsOptions = Field(default_factory=TotalsOptions)
    # Phase 7 addition — display options (number/date format, conditional
    # formats, frozen + hidden columns). Default empty; safe no-op.
    display_options: DisplayOptions = Field(default_factory=DisplayOptions, alias="displayOptions")

    model_config = {"populate_by_name": True}


class PivotMetadata(BaseModel):
    dataset_id: int
    sheet_name: str
    source_rows: int
    filtered_rows: int
    layout: str
    rows: List[str]
    columns: List[str]
    date_grouping: Dict[str, str]
    sorting: Dict[str, str] = Field(default_factory=dict)
    totals: TotalsOptions = Field(default_factory=TotalsOptions)
    display_options: DisplayOptions = Field(default_factory=DisplayOptions)


class PivotResponse(BaseModel):
    rows: List[Dict[str, Any]]
    columns: List[str]
    totals: Dict[str, Any]
    metadata: PivotMetadata
    aggregations: List[Dict[str, str]]


class PivotValidateRequest(PivotRequest):
    """Alias — used by /api/pivot/validate. Same shape as PivotRequest."""
    pass


class PivotValidateResponse(BaseModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)
    per_value_field: Dict[str, Any] = Field(default_factory=dict)


class PivotDrilldownRequest(PivotRequest):
    """Request contract for POST /api/pivot/drilldown."""

    selection: Dict[str, Any] = Field(default_factory=dict)
    limit: int = 500


class PivotDrilldownResponse(BaseModel):
    rows: List[Dict[str, Any]]
    columns: List[str]
    metadata: Dict[str, Any]
