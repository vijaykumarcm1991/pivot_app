"""
Email service — Phase 6.

The orchestrator that ties together:
  - attachment_service  → build the .xlsx file
  - smtp_service        → connect and send
  - email_history_*     → record the outcome

Also builds the HTML email body (the "Pivot Summary" + user message
+ footer). The HTML is intentionally written with table-based layout
and inline CSS so it renders correctly in Outlook and Gmail.

The service is the only place that knows the full email lifecycle
for a pivot. Frontend code should call `compose_preview` to render
the preview, and `compose_and_send` to actually send the email.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config.settings import REPORTS_DIR
from app.repositories import smtp_settings_repository, email_history_repository
from app.services.attachment_service import (
    AttachmentError,
    build_attachment,
    save_attachment,
)
from app.services.smtp_service import SMTPError, is_complete, send_email
from app.schemas.email import EmailSendRequest
from app.utils.tz import format_ist, now_ist


# ── Public types ─────────────────────────────────────────────────────────

class EmailValidationError(ValueError):
    """Raised when the request fails validation (addresses, SMTP, etc.)."""


class EmailResult:
    """A friendly handle returned by `compose_preview` so the
    frontend can download the attachment and inspect the metadata
    without re-fetching anything from the server."""

    def __init__(
        self,
        html: str,
        subject: str,
        attachment_filename: str,
        attachment_download_url: str,
        attachment_record_count: int,
        matched_rows: int,
        pivot_rows_count: int,
        dataset_name: str,
        sheet_name: str,
        generated_at: datetime,
    ) -> None:
        self.html = html
        self.subject = subject
        self.attachment_filename = attachment_filename
        self.attachment_download_url = attachment_download_url
        self.attachment_record_count = attachment_record_count
        self.matched_rows = matched_rows
        self.pivot_rows_count = pivot_rows_count
        self.dataset_name = dataset_name
        self.sheet_name = sheet_name
        self.generated_at = generated_at


# ── Public API ──────────────────────────────────────────────────────────

# Very small RFC 5322-ish check. Good enough for catching typos
# before we open an SMTP connection.
_EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def parse_address_list(raw: Any) -> List[str]:
    """Accept a string, a list, or None and return a clean list of
    addresses. Supports both comma and semicolon as separators so
    users can paste either format."""

    if raw is None:
        return []
    if isinstance(raw, str):
        # Split on commas, semicolons, or newlines.
        parts = re.split(r"[,;\n]+", raw)
    elif isinstance(raw, list):
        parts = []
        for item in raw:
            if isinstance(item, str):
                parts.extend(re.split(r"[,;\n]+", item))
            else:
                parts.append(str(item))
    else:
        parts = [str(raw)]

    return [p.strip() for p in parts if p and p.strip()]


def validate_addresses(addresses: List[str], field: str) -> List[str]:
    """Return the list unchanged if every address is valid, raise
    EmailValidationError otherwise."""

    cleaned: List[str] = []
    for a in addresses:
        a = (a or "").strip()
        if not a:
            continue
        if not _EMAIL_REGEX.match(a):
            raise EmailValidationError(f"Invalid {field} address: '{a}'")
        cleaned.append(a)
    if not cleaned:
        return cleaned
    # de-duplicate, case-insensitively
    seen = set()
    deduped: List[str] = []
    for a in cleaned:
        key = a.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(a)
    return deduped


def validate_request(request: EmailSendRequest) -> Dict[str, List[str]]:
    """Validate the inbound request — addresses + subject.
    Returns a dict with the cleaned {to, cc, bcc} lists."""

    to = validate_addresses(parse_address_list(request.to), "To")
    cc = validate_addresses(parse_address_list(request.cc), "CC")
    bcc = validate_addresses(parse_address_list(request.bcc), "BCC")

    if not (to or cc or bcc):
        raise EmailValidationError("At least one recipient is required (To, CC, or BCC).")

    if not (request.subject or "").strip():
        raise EmailValidationError("Subject is required.")

    if not request.selections:
        raise EmailValidationError("No pivot rows selected — nothing to send.")

    return {"to": to, "cc": cc, "bcc": bcc}


def compose_preview(
    db: Session,
    request: EmailSendRequest,
) -> EmailResult:
    """Build the HTML body + the attachment but DO NOT send.
    Returns an EmailResult the frontend can render and offer a
    download link for the attachment."""

    cleaned = validate_request(request)

    # ── Build attachment ────────────────────────────────────────────
    try:
        attachment_bytes, attachment_filename, matched, returned = build_attachment(
            db=db,
            dataset_id=request.datasetId,
            sheet_name=request.sheetName,
            rows=request.rows,
            columns=request.columns,
            values=request.values,
            filters=request.filters,
            date_grouping=request.dateGrouping,
            sorting=request.sorting,
            totals=request.totals,
            layout=request.layout,
            selections=[s.selection for s in request.selections],
            dataset_name=request.dataset_name,
            sheet_label=request.sheetName,
        )
    except AttachmentError as exc:
        raise EmailValidationError(str(exc)) from exc

    # Stash the attachment in REPORTS_DIR so the preview-download
    # route can serve it back to the user without re-generating.
    rel_path = save_attachment(attachment_bytes, attachment_filename, subdir="email_previews")

    # ── Build HTML ─────────────────────────────────────────────────
    pivot_response = request.pivot_response or {}
    html = build_email_html(
        subject=request.subject,
        message=request.message or "",
        pivot_rows=request.pivot_rows or [],
        pivot_response=pivot_response,
        dataset_name=request.dataset_name or "",
        sheet_name=request.sheetName or "",
    )

    generated_at = datetime.utcnow()
    download_url = f"/api/email/preview-attachment/{rel_path}"

    return EmailResult(
        html=html,
        subject=request.subject,
        attachment_filename=attachment_filename,
        attachment_download_url=download_url,
        attachment_record_count=returned,
        matched_rows=matched,
        pivot_rows_count=len(request.pivot_rows or []),
        dataset_name=request.dataset_name or "",
        sheet_name=request.sheetName or "",
        generated_at=generated_at,
    )


def compose_and_send(
    db: Session,
    request: EmailSendRequest,
) -> Dict[str, Any]:
    """Validate, build the attachment, build the HTML, send via
    SMTP, and record the outcome. Returns a small dict with the
    history id and status so the frontend can show a success or
    error toast."""

    cleaned = validate_request(request)

    smtp = smtp_settings_repository.get_settings(db)
    if not is_complete(smtp):
        raise EmailValidationError(
            "SMTP settings are incomplete. Open the Email Settings "
            "page and fill in host, port, username, password, "
            "sender name and sender email."
        )

    # ── Build attachment ────────────────────────────────────────────
    try:
        attachment_bytes, attachment_filename, matched, returned = build_attachment(
            db=db,
            dataset_id=request.datasetId,
            sheet_name=request.sheetName,
            rows=request.rows,
            columns=request.columns,
            values=request.values,
            filters=request.filters,
            date_grouping=request.dateGrouping,
            sorting=request.sorting,
            totals=request.totals,
            layout=request.layout,
            selections=[s.selection for s in request.selections],
            dataset_name=request.dataset_name,
            sheet_label=request.sheetName,
        )
    except AttachmentError as exc:
        raise EmailValidationError(str(exc)) from exc

    # ── Persist attachment for re-download ──────────────────────────
    rel_path = save_attachment(attachment_bytes, attachment_filename, subdir="email_attachments")

    # ── Build HTML ─────────────────────────────────────────────────
    pivot_response = request.pivot_response or {}
    html = build_email_html(
        subject=request.subject,
        message=request.message or "",
        pivot_rows=request.pivot_rows or [],
        pivot_response=pivot_response,
        dataset_name=request.dataset_name or "",
        sheet_name=request.sheetName or "",
    )

    # ── Record history BEFORE sending (so we can update it after) ──
    history = email_history_repository.create_history(
        db,
        sent_at=datetime.utcnow(),
        subject=request.subject,
        to_addresses_json=json.dumps(cleaned["to"]),
        cc_addresses_json=json.dumps(cleaned["cc"]),
        bcc_addresses_json=json.dumps(cleaned["bcc"]),
        dataset_id=request.datasetId,
        dataset_name=request.dataset_name or "",
        sheet_name=request.sheetName or "",
        pivot_rows_count=len(request.pivot_rows or []),
        attached_records_count=returned,
        status="failed",
        attachment_filename=attachment_filename,
        attachment_path=rel_path,
        pivot_payload_json=json.dumps(_payload_snapshot(request)),
    )

    # ── Send via SMTP ──────────────────────────────────────────────
    try:
        send_email(
            smtp,
            to=cleaned["to"],
            cc=cleaned["cc"],
            bcc=cleaned["bcc"],
            subject=request.subject,
            html_body=html,
            attachment_bytes=attachment_bytes,
            attachment_filename=attachment_filename,
        )
    except SMTPError as exc:
        email_history_repository.update_history(
            db, history.id, status="failed", error_message=str(exc),
        )
        # Remember the recipients anyway -- the failure is on the
        # SMTP server side, not a typo in the address. Skipping
        # would lose useful autocomplete suggestions.
        _remember_recipients(db, cleaned)
        raise

    # Mark as success and remember recipients
    email_history_repository.update_history(db, history.id, status="success")
    _remember_recipients(db, cleaned)

    return {
        "history_id": history.id,
        "status": "success",
        "sent_at": history.sent_at.isoformat(),
        # Return the datetime as well so the route can produce
        # the IST-formatted string for the frontend. (isoformat()
        # on a naive datetime does NOT include the tz suffix; the
        # route can use `iso_ist(history.sent_at)` instead.)
        "sent_at_dt": history.sent_at,
        "attachment_filename": attachment_filename,
        "attached_records_count": returned,
    }


def _remember_recipients(db, cleaned):
    # Persist the just-sent addresses to recent_recipients so the
    # autocomplete has fresh suggestions next time the user opens the
    # composer. Called on both success and failure.
    for addr in cleaned.get("to", []):
        email_history_repository.upsert_recent_recipient(db, addr, "to")
    for addr in cleaned.get("cc", []):
        email_history_repository.upsert_recent_recipient(db, addr, "cc")
    for addr in cleaned.get("bcc", []):
        email_history_repository.upsert_recent_recipient(db, addr, "bcc")


# ── HTML body ───────────────────────────────────────────────────────────

def build_email_html(
    *,
    subject: str,
    message: str,
    pivot_rows: List[Dict[str, Any]],
    pivot_response: Dict[str, Any],
    dataset_name: str,
    sheet_name: str,
) -> str:
    """Build the full HTML email body. Uses inline CSS and a
    table-based layout for Outlook/Gmail compatibility. Returns
    a complete <html> document."""

    safe_subject = _html_escape(subject or "")
    safe_message_html = _message_to_html(message or "")
    safe_dataset = _html_escape(dataset_name or "—")
    safe_sheet = _html_escape(sheet_name or "—")
    # Generated On is shown in the configured timezone (default IST).
    # The user explicitly asked for IST everywhere — every visible
    # timestamp in the app is formatted in the timezone set on the
    # singleton app_settings row (default: Asia/Kolkata).
    generated_on = format_ist(now_ist(), fmt="%d %b %Y, %H:%M:%S IST")

    pivot_table_html = _pivot_rows_to_html(pivot_rows, pivot_response)
    # The grand-total row is intentionally NOT rendered — it was
    # coming out blank in V1 because the engine returns `grand`
    # keyed by value-label, not by column, and the column-name
    # alignment is fragile. The user asked to drop the grand-total
    # block entirely. All totals are still in the .xlsx attachment.
    grand_total_html = ""

    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_subject}</title>
  <!--[if gte mso 9]>
  <xml>
    <o:OfficeDocumentSettings>
      <o:PixelsPerInch>96</o:PixelsPerInch>
    </o:OfficeDocumentSettings>
  </xml>
  <![endif]-->
</head>
<body style="margin:0;padding:0;background-color:#f5f5f5;font-family:Helvetica,Arial,sans-serif;color:#222;">
  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color:#f5f5f5;padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="640" style="max-width:640px;background-color:#ffffff;border:1px solid #e0e0e0;border-radius:6px;overflow:hidden;">
          <tr>
            <td style="background-color:#0d6efd;color:#ffffff;padding:16px 24px;font-size:18px;font-weight:bold;">
              {safe_subject}
            </td>
          </tr>
          <tr>
            <td style="padding:24px;font-size:14px;line-height:1.55;color:#222;">
              {safe_message_html}
            </td>
          </tr>
          {pivot_table_html}
          {grand_total_html}
          <tr>
            <td style="padding:16px 24px;font-size:12px;line-height:1.5;color:#666;border-top:1px solid #e0e0e0;">
              <div><strong>Generated By:</strong> Pivot App</div>
              <div><strong>Generated On:</strong> {generated_on}</div>
              <div><strong>Dataset:</strong> {safe_dataset}</div>
              <div><strong>Sheet:</strong> {safe_sheet}</div>
            </td>
          </tr>
        </table>
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="640" style="max-width:640px;">
          <tr>
            <td style="padding:12px 24px;font-size:11px;color:#999;text-align:center;">
              Sent by Pivot App &middot; an internal Excel pivot + email tool.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _pivot_rows_to_html(
    pivot_rows: List[Dict[str, Any]],
    pivot_response: Dict[str, Any],
) -> str:
    """Render the selected pivot rows as an HTML table. Column
    order is taken from the engine's `columns` array so the
    order matches the user's pivot UI exactly. We also render
    any per-row `row_total` value if it is present."""

    if not pivot_rows:
        return ""

    columns = list((pivot_response or {}).get("columns") or [])
    if not columns:
        # Derive a column list from the union of keys.
        seen = []
        for row in pivot_rows:
            for k in row.keys():
                if k not in seen and not k.startswith("__"):
                    seen.append(k)
        columns = seen

    # Render header
    header_cells = "".join(
        f'<th style="padding:8px 12px;background-color:#f0f0f0;border:1px solid #ddd;'
        f'text-align:left;font-size:12px;font-weight:bold;color:#333;">'
        f'{_html_escape(str(c))}</th>'
        for c in columns
    )

    body_rows = []
    for row in pivot_rows:
        cells = "".join(
            f'<td style="padding:6px 12px;border:1px solid #ddd;'
            f'font-size:12px;color:#222;{_cell_text_align(c, row.get(c))}">'
            f'{_html_escape(str(row.get(c, "")))}</td>'
            for c in columns
        )
        body_rows.append(f"<tr>{cells}</tr>")

    return f"""
          <tr>
            <td style=\"padding:0 24px 16px 24px;\">
              <table role=\"presentation\" border=\"0\" cellpadding=\"0\" cellspacing=\"0\" width=\"100%\" style=\"border-collapse:collapse;\">
                <thead><tr>{header_cells}</tr></thead>
                <tbody>{''.join(body_rows)}</tbody>
              </table>
            </td>
          </tr>
"""


# ── Small HTML helpers ──────────────────────────────────────────────────

def _html_escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _message_to_html(message: str) -> str:
    """Convert a plain-text user message into a minimal HTML block.
    We preserve newlines as <br> and escape any HTML so the user
    cannot inject markup into the email."""
    safe = _html_escape(message).replace("\n", "<br>")
    return f'<div style="white-space:normal;">{safe}</div>'


def _cell_text_align(column: str, value: Any) -> str:
    """Right-align numeric-looking cells so the column lines up."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "text-align:right;"
    if column in {"row_total"} or (isinstance(column, str) and column.startswith("sum_")):
        return "text-align:right;"
    return "text-align:left;"


def _payload_snapshot(request: EmailSendRequest) -> Dict[str, Any]:
    """Capture a minimal JSON-serialisable snapshot of the request
    so the history page can later re-render the email body
    without re-querying the dataset. Pivot rows and selections
    are kept verbatim; everything else is summarised."""
    return {
        "datasetId": request.datasetId,
        "sheetName": request.sheetName,
        "dataset_name": request.dataset_name,
        "pivot_rows": request.pivot_rows,
        "pivot_response": request.pivot_response,
        "selections": [s.selection for s in request.selections],
    }
