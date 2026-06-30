"""
SMTP service — Phase 6.

Thin wrapper around Python's `smtplib` and `email.message.EmailMessage`
that knows how to connect to the user's SMTP server, sign in, and
send a message with an HTML body and a single Excel attachment.

Configuration is read from the `smtp_settings` table on every send
(the singleton row id=1). The password is currently stored as
plaintext for Version 1; production should encrypt it at rest.

This module deliberately knows nothing about the pivot or the
attachment. It just sends a pre-built `EmailMessage`. The
orchestration lives in `email_service.py`.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from typing import List, Optional

from app.models.smtp_settings import SMTPSettings


class SMTPError(RuntimeError):
    """Raised when the SMTP server cannot be reached, the credentials
    are rejected, or the message cannot be sent."""


def send_email(
    settings: SMTPSettings,
    *,
    to: List[str],
    cc: List[str],
    bcc: List[str],
    subject: str,
    html_body: str,
    attachment_bytes: Optional[bytes] = None,
    attachment_filename: Optional[str] = None,
    attachment_mimetype: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
) -> None:
    """Send a single email through the configured SMTP server.

    - `to`, `cc`, `bcc` are lists of addresses (already validated
      by the email service).
    - `html_body` is a complete HTML document; the function wraps
      it in a multipart/alternative message so the recipient
      always sees a readable version.
    - If `attachment_bytes` is set, the file is attached with the
      given filename and MIME type.

    Raises `SMTPError` on any failure — the email service catches
    it and records the failure in the history table.
    """

    if settings is None:
        raise SMTPError("SMTP settings are not configured.")

    if not settings.host:
        raise SMTPError("SMTP host is not configured.")
    if not settings.sender_email:
        raise SMTPError("Sender email is not configured.")

    # Defensive copy / strip empties so we never send to " " or "".
    def _clean(addresses: List[str]) -> List[str]:
        seen = set()
        out = []
        for a in addresses or []:
            a = (a or "").strip()
            if not a:
                continue
            key = a.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(a)
        return out

    to_clean = _clean(to)
    cc_clean = _clean(cc)
    bcc_clean = _clean(bcc)

    if not (to_clean or cc_clean or bcc_clean):
        raise SMTPError("At least one recipient is required.")

    msg = EmailMessage()
    msg["Subject"] = (subject or "").strip() or "(no subject)"
    sender_name = (settings.sender_name or "").strip()
    if sender_name:
        msg["From"] = f"{sender_name} <{settings.sender_email}>"
    else:
        msg["From"] = settings.sender_email
    if to_clean:
        msg["To"] = ", ".join(to_clean)
    if cc_clean:
        msg["Cc"] = ", ".join(cc_clean)
    # BCC is intentionally NOT in the headers (that's the point of
    # bcc) but the recipients still receive the message.
    msg.set_content(
        "This email requires an HTML-capable client. Please view "
        "it in a modern mail client."
    )
    msg.add_alternative(html_body, subtype="html")

    if attachment_bytes and attachment_filename:
        msg.add_attachment(
            attachment_bytes,
            maintype=attachment_mimetype.split("/", 1)[0],
            subtype=attachment_mimetype.split("/", 1)[1],
            filename=attachment_filename,
        )

    recipients: List[str] = to_clean + cc_clean + bcc_clean

    # Connect + send
    try:
        if settings.use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(settings.host, int(settings.port), timeout=30) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                if settings.username:
                    server.login(settings.username, settings.password or "")
                server.send_message(msg, from_addr=settings.sender_email, to_addrs=recipients)
        else:
            with smtplib.SMTP(settings.host, int(settings.port), timeout=30) as server:
                server.ehlo()
                if settings.username:
                    server.login(settings.username, settings.password or "")
                server.send_message(msg, from_addr=settings.sender_email, to_addrs=recipients)
    except smtplib.SMTPAuthenticationError as exc:
        raise SMTPError(f"SMTP authentication failed: {exc}") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise SMTPError(f"All recipients were refused: {exc}") from exc
    except smtplib.SMTPException as exc:
        raise SMTPError(f"SMTP error: {exc}") from exc
    except (OSError, TimeoutError) as exc:
        raise SMTPError(f"Could not reach SMTP server: {exc}") from exc


def is_complete(settings: Optional[SMTPSettings]) -> bool:
    """Return True if the settings are enough to actually send an
    email. Used by the frontend to enable/disable the Send button
    and by the backend to fail fast."""

    if settings is None:
        return False
    if not (settings.host and settings.port and settings.sender_email):
        return False
    # username + password are only required if the server demands
    # them, but we treat them as required in the form for simplicity.
    if not settings.username:
        return False
    return True
