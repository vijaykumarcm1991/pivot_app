"""SMTP password is encrypted at rest and decrypted only for login."""
import smtplib


def _row():
    from app.config.database import SessionLocal
    from app.repositories.smtp_settings_repository import get_settings

    db = SessionLocal()
    try:
        row = get_settings(db)
        return db, row
    except Exception:
        db.close()
        raise


SETTINGS = {
    "host": "smtp.example.com", "port": 587, "username": "bot@example.com",
    "password": "s3cret-pass", "useTls": True,
    "senderName": "Bot", "senderEmail": "bot@example.com",
}


def test_password_is_encrypted_and_never_returned(client):
    res = client.post("/api/email/smtp-settings", json=SETTINGS)
    assert res.status_code == 200
    assert res.json()["passwordSet"] is True
    assert "s3cret" not in res.text

    db, row = _row()
    try:
        assert row.password.startswith("enc:v1:")
        assert "s3cret" not in row.password
        from app.repositories.smtp_settings_repository import plaintext_password
        assert plaintext_password(row) == "s3cret-pass"
    finally:
        db.close()


def test_blank_password_keeps_existing(client):
    client.post("/api/email/smtp-settings", json=SETTINGS)
    client.post("/api/email/smtp-settings", json={**SETTINGS, "password": ""})
    db, row = _row()
    try:
        from app.repositories.smtp_settings_repository import plaintext_password
        assert plaintext_password(row) == "s3cret-pass"
    finally:
        db.close()


def test_legacy_plaintext_is_encrypted(client):
    from app.repositories.smtp_settings_repository import encrypt_legacy_password, plaintext_password

    client.post("/api/email/smtp-settings", json=SETTINGS)
    db, row = _row()
    try:
        row.password = "old-plain"
        db.commit()
        assert encrypt_legacy_password(db) is True
        db.refresh(row)
        assert row.password.startswith("enc:v1:")
        assert plaintext_password(row) == "old-plain"
        assert encrypt_legacy_password(db) is False
    finally:
        db.close()


def test_send_logs_in_with_decrypted_password(client, monkeypatch):
    from app.services.smtp_service import send_email

    client.post("/api/email/smtp-settings", json=SETTINGS)
    seen = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def ehlo(self): pass
        def starttls(self, **k): pass
        def login(self, user, pw): seen["login"] = (user, pw)
        def send_message(self, msg, from_addr, to_addrs): seen["to"] = to_addrs

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    db, row = _row()
    try:
        send_email(row, to=["a@example.com"], cc=[], bcc=[], subject="s", html_body="<p>x</p>")
    finally:
        db.close()
    assert seen["login"] == ("bot@example.com", "s3cret-pass")
    assert seen["to"] == ["a@example.com"]


def test_relay_without_login(client, monkeypatch):
    from app.services.smtp_service import is_complete, send_email

    client.post("/api/email/smtp-settings", json={**SETTINGS, "username": "", "password": ""})
    calls = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def ehlo(self): pass
        def starttls(self, **k): pass
        def login(self, *a): calls["login"] = a
        def send_message(self, msg, from_addr, to_addrs): calls["sent"] = to_addrs

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    db, row = _row()
    try:
        assert row.username == "" and row.password == ""
        assert is_complete(row)
        send_email(row, to=["a@example.com"], cc=[], bcc=[], subject="s", html_body="x")
        assert "login" not in calls and calls["sent"] == ["a@example.com"]
        row.username = "someone"
        assert not is_complete(row)  # username without password
    finally:
        db.close()
