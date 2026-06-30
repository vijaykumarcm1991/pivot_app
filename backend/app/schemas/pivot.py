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
