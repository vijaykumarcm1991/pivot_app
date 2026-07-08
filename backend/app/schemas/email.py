"""
Pydantic schemas for Phase 6 — Email composition.

We deliberately keep the request contract independent of the existing
PivotRequest so the email endpoint can accept the same payload the
client already uses for /api/pivot plus a small email-specific block.

All field names are camelCase on the wire (the same convention the
rest of the API uses — see `pivot.py`). `populate_by_name=True` lets
callers use either form.
"""
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── SMTP settings ────────────────────────────────────────────────────────

class SMTPSettingsOut(BaseModel):
    """Public-facing SMTP settings. The password is never returned to
    the client (returned as a boolean `password_set` instead)."""

    model_config = ConfigDict(populate_by_name=True)

    host: str
    port: int
    username: str
    password_set: bool = Field(alias="passwordSet")
    use_tls: bool = Field(alias="useTls")
    sender_name: str = Field(alias="senderName")
    sender_email: str = Field(alias="senderEmail")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt")
    # IST-formatted ISO-8601 string for the frontend.
    updated_at_ist: Optional[str] = Field(default=None, alias="updatedAtIst")


class SMTPSettingsIn(BaseModel):
    """Inbound SMTP settings. `password` may be empty — if so, the
    existing password is kept (so the UI can show `•••••••` and only
    require a new value when the user explicitly changes it)."""

    model_config = ConfigDict(populate_by_name=True)

    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = Field(default=True, alias="useTls")
    sender_name: str = Field(default="", alias="senderName")
    sender_email: str = Field(default="", alias="senderEmail")

    @field_validator("port")
    @classmethod
    def _port_in_range(cls, v: int) -> int:
        if v < 1 or v > 65535:
            raise ValueError("port must be between 1 and 65535")
        return v


# ── Email send / preview ────────────────────────────────────────────────

class EmailPivotSelection(BaseModel):
    """One selected pivot row, expressed as a flat { field: value }
    map. The keys are the row field names (or their date-grouped
    display names) and the values are the values the user sees in
    the pivot result row."""

    model_config = ConfigDict(populate_by_name=True)

    selection: Dict[str, Any]


class EmailSendRequest(BaseModel):
    """Request body for /api/email/preview and /api/email/send."""

    model_config = ConfigDict(populate_by_name=True)

    # Email content. Each recipient field accepts either a JSON
    # list of addresses or a single string with addresses
    # separated by commas / semicolons / newlines — the service
    # parses both shapes via `parse_address_list`.
    to: Union[str, List[str]] = Field(default_factory=list)
    cc: Union[str, List[str]] = Field(default_factory=list)
    bcc: Union[str, List[str]] = Field(default_factory=list)
    subject: str = ""
    message: str = ""

    # Pivot context (same shape as /api/pivot, but minus the
    # per-render fields we don't need for the email).
    datasetId: int
    sheetName: str
    rows: List[str] = Field(default_factory=list)
    columns: List[str] = Field(default_factory=list)
    values: List[Any] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
    dateGrouping: Dict[str, str] = Field(default_factory=dict)
    sorting: Dict[str, str] = Field(default_factory=dict)
    totals: Dict[str, Any] = Field(default_factory=dict)
    layout: str = "tabular"

    # The list of selected pivot rows. Each item is a
    # { selection: {field:value} } map.
    selections: List[EmailPivotSelection] = Field(default_factory=list)

    # The selected pivot row data (for the HTML summary).
    # Each item is the raw pivot row object.
    pivot_rows: List[Dict[str, Any]] = Field(default_factory=list)

    # The full PivotResponse metadata (column list, totals, etc.)
    # so the server can render the same summary the user saw.
    pivot_response: Dict[str, Any] = Field(default_factory=dict)

    # Filename of the uploaded dataset (for the footer).
    dataset_name: str = ""


class EmailPreviewResponse(BaseModel):
    """Response from /api/email/preview — the rendered HTML body,
    the list of recipients, and a one-shot download URL for the
    generated attachment."""

    model_config = ConfigDict(populate_by_name=True)

    html: str
    subject: str
    to: List[str]
    cc: List[str]
    bcc: List[str]
    attachment_filename: str = Field(alias="attachmentFilename")
    attachment_download_url: str = Field(alias="attachmentDownloadUrl")
    attachment_record_count: int = Field(alias="attachmentRecordCount")
    matched_rows: int = Field(alias="matchedRows")
    pivot_rows_count: int = Field(alias="pivotRowsCount")
    dataset_name: str = Field(alias="datasetName")
    sheet_name: str = Field(alias="sheetName")
    generated_at: str = Field(alias="generatedAt")
    # IST-formatted ISO-8601 string for the frontend.
    generated_at_ist: Optional[str] = Field(default=None, alias="generatedAtIst")


class EmailSendResponse(BaseModel):
    """Response from /api/email/send."""

    model_config = ConfigDict(populate_by_name=True)

    history_id: int = Field(alias="historyId")
    status: str
    error_message: Optional[str] = Field(default=None, alias="errorMessage")
    sent_at: str = Field(alias="sentAt")
    # IST-formatted ISO-8601 string for the frontend.
    sent_at_ist: Optional[str] = Field(default=None, alias="sentAtIst")


# ── Email history ────────────────────────────────────────────────────────

class EmailHistoryOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    sent_at: str = Field(alias="sentAt")
    # IST-formatted ISO-8601 string for the frontend (e.g.
    # "2026-07-08T14:32:33+05:30").  The frontend can either render
    # this directly or pass it to AppFormat.ist() for a human-
    # readable label.
    sent_at_ist: Optional[str] = Field(default=None, alias="sentAtIst")
    subject: str
    to_addresses: List[str] = Field(alias="toAddresses")
    cc_addresses: List[str] = Field(alias="ccAddresses")
    bcc_addresses: List[str] = Field(alias="bccAddresses")
    dataset_id: Optional[int] = Field(default=None, alias="datasetId")
    dataset_name: Optional[str] = Field(default=None, alias="datasetName")
    sheet_name: Optional[str] = Field(default=None, alias="sheetName")
    pivot_rows_count: int = Field(alias="pivotRowsCount")
    attached_records_count: int = Field(alias="attachedRecordsCount")
    status: str
    error_message: Optional[str] = Field(default=None, alias="errorMessage")
    attachment_filename: Optional[str] = Field(default=None, alias="attachmentFilename")
    has_attachment: bool = Field(alias="hasAttachment")


# ── Recent recipients ────────────────────────────────────────────────────

class RecentRecipientOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    address: str
    recipient_type: str = Field(alias="recipientType")
    last_used_at: str = Field(alias="lastUsedAt")
    # IST-formatted ISO-8601 string for the frontend.
    last_used_at_ist: Optional[str] = Field(default=None, alias="lastUsedAtIst")
    use_count: int = Field(alias="useCount")
