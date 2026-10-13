"""Saved pivots, email templates, dataset refresh, restore, schedules."""
import io
import smtplib
from datetime import datetime

import pandas as pd
import pytest


DATA = pd.DataFrame({
    "Cat": ["A", "A", "B", "C", "C", "C"],
    "Unit": ["X", "Y", "X", "X", "Y", "Y"],
    "N": [1, 2, 3, 4, 5, 6],
})

SMTP = {"host": "smtp.example.com", "port": 587, "username": "bot@example.com",
        "password": "pw", "useTls": True, "senderName": "Bot", "senderEmail": "bot@example.com"}


def _config(ds, **extra):
    return {"datasetId": ds, "sheetName": "Sheet1", "rows": ["Cat"],
            "values": [{"field": "N", "aggregation": "sum", "label": "sum_N"}], **extra}


def _csv(df):
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


@pytest.fixture
def fake_smtp(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def ehlo(self): pass
        def starttls(self, **k): pass
        def login(self, *a): pass
        def send_message(self, msg, from_addr, to_addrs):
            sent.append({"subject": msg["Subject"], "to": to_addrs, "msg": msg})

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    return sent


# ── Saved pivots ────────────────────────────────────────────────────────

def test_saved_pivot_crud(client, upload):
    ds = upload(DATA)
    res = client.post("/api/saved-pivots", json={
        "name": "By category", "config": _config(ds, availableColumns=["x"], datasetName="d")})
    assert res.status_code == 201, res.text
    sp = res.json()
    assert "availableColumns" not in sp["config"]
    assert client.post("/api/saved-pivots", json={"name": "by CATEGORY", "config": _config(ds)}).status_code == 409

    listed = client.get(f"/api/saved-pivots?dataset_id={ds}").json()
    assert [s["name"] for s in listed] == ["By category"]

    upd = client.put(f"/api/saved-pivots/{sp['id']}", json={"config": _config(ds, layout="compact")})
    assert upd.json()["config"]["layout"] == "compact"

    bad = client.post("/api/saved-pivots", json={"name": "Bad", "config": {"rows": ["Cat"]}})
    assert bad.status_code == 400

    assert client.delete(f"/api/saved-pivots/{sp['id']}").status_code == 200
    assert client.get(f"/api/saved-pivots/{sp['id']}").status_code == 404


def test_deleting_dataset_removes_saved_pivots(client, upload):
    ds = upload(DATA)
    sp = client.post("/api/saved-pivots", json={"name": f"tmp-{ds}", "config": _config(ds)}).json()
    client.delete(f"/api/dataset/{ds}")
    assert client.get(f"/api/saved-pivots/{sp['id']}").status_code == 404


# ── Email templates + placeholders ──────────────────────────────────────

def test_email_template_crud(client):
    res = client.post("/api/email/templates", json={
        "name": "Daily ops", "subject": "Alerts {date}", "message": "Hi", "to": "ops@example.com"})
    assert res.status_code == 201, res.text
    tid = res.json()["id"]
    assert client.post("/api/email/templates", json={"name": "daily OPS"}).status_code == 409
    assert client.put(f"/api/email/templates/{tid}", json={"name": "Daily ops", "subject": "S2"}).json()["subject"] == "S2"
    assert any(t["id"] == tid for t in client.get("/api/email/templates").json())
    assert client.delete(f"/api/email/templates/{tid}").status_code == 200


def test_placeholders_rendered_in_preview(client, upload):
    ds = upload(DATA)
    res = client.post("/api/email/preview", json={
        "to": "a@example.com", "subject": "{dataset} / {sheet} — {rows} rows {unknown}",
        "message": "Report for {date}", "datasetId": ds, "sheetName": "Sheet1", "rows": ["Cat"],
        "selections": [{"selection": {"Cat": "A"}}], "pivot_rows": [{"Cat": "A"}],
        "dataset_name": "ops.csv",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["subject"] == "ops.csv / Sheet1 — 1 rows {unknown}"
    assert "{date}" not in body["html"]


# ── Dataset refresh ─────────────────────────────────────────────────────

def test_refresh_keeps_id_deletes_and_warns(client, upload):
    ds = upload(DATA)
    pr = {"datasetId": ds, "sheetName": "Sheet1", "rows": ["Cat"], "values": []}
    client.post("/api/pivot/delete-records", json={"pivotRequest": pr, "selections": [{"Cat": "B"}]})
    client.post("/api/saved-pivots", json={"name": f"by unit {ds}", "config": {**_config(ds), "rows": ["Unit"]}})

    new = pd.concat([DATA, pd.DataFrame({"Cat": ["D"], "Unit": ["Z"], "N": [9]})]).drop(columns=["Unit"])
    res = client.post(f"/api/dataset/{ds}/refresh",
                      files={"file": ("today.csv", _csv(new), "text/csv")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["datasetId"] == ds and body["totalRows"] == 7 and body["filename"] == "today.csv"
    assert any("Unit" in w for w in body["warnings"])

    pivot = client.post("/api/pivot", json=pr).json()
    assert "D" in [r.get("Cat") for r in pivot["rows"]]
    assert client.get(f"/api/dataset/{ds}").json()["total_rows"] == 7


def test_refresh_keeps_identical_deleted_records_hidden(client, upload):
    ds = upload(DATA)
    pr = {"datasetId": ds, "sheetName": "Sheet1", "rows": ["Cat"], "values": []}
    client.post("/api/pivot/delete-records", json={"pivotRequest": pr, "selections": [{"Cat": "B"}]})
    res = client.post(f"/api/dataset/{ds}/refresh", files={"file": ("same.csv", _csv(DATA), "text/csv")})
    assert res.status_code == 200
    pivot = client.post("/api/pivot", json=pr).json()
    assert "B" not in [r.get("Cat") for r in pivot["rows"]]


def test_refresh_rejects_bad_file_and_keeps_dataset(client, upload):
    ds = upload(DATA)
    res = client.post(f"/api/dataset/{ds}/refresh", files={"file": ("x.txt", b"nope", "text/plain")})
    assert res.status_code == 400
    assert client.get(f"/api/dataset/{ds}").json()["total_rows"] == 6


# ── Restore ─────────────────────────────────────────────────────────────

def test_restore_brings_records_back_once(client, upload):
    ds = upload(DATA)
    pr = {"datasetId": ds, "sheetName": "Sheet1", "rows": ["Cat"], "values": []}
    audit_id = client.post("/api/pivot/delete-records",
                           json={"pivotRequest": pr, "selections": [{"Cat": "C"}]}).json()["auditId"]
    assert "C" not in [r.get("Cat") for r in client.post("/api/pivot", json=pr).json()["rows"]]

    res = client.post(f"/api/admin/audit/{audit_id}/restore")
    assert res.status_code == 200 and res.json()["restored"] == 3
    assert "C" in [r.get("Cat") for r in client.post("/api/pivot", json=pr).json()["rows"]]
    assert client.post(f"/api/admin/audit/{audit_id}/restore").status_code == 400
    entry = next(r for r in client.get(f"/api/admin/audit?dataset_id={ds}").json()["rows"] if r["id"] == audit_id)
    assert entry["status"] == "restored" and entry["restorable"] is False
    assert client.post("/api/admin/audit/999999/restore").status_code == 404


# ── Schedules ───────────────────────────────────────────────────────────

def test_compute_next_run_variants():
    from app.models.report_schedule import ReportSchedule
    from app.services.scheduler_service import compute_next_run

    s = ReportSchedule(frequency="weekdays", run_time="09:00", weekdays="0", day_of_month=1)
    # Fri 2026-10-16 10:00 IST (04:30 UTC) → next is Mon 09:00 IST = 03:30 UTC
    assert compute_next_run(s, datetime(2026, 10, 16, 4, 30), "Asia/Kolkata") == datetime(2026, 10, 19, 3, 30)
    s.frequency = "daily"
    assert compute_next_run(s, datetime(2026, 10, 16, 3, 0), "Asia/Kolkata") == datetime(2026, 10, 16, 3, 30)
    s.frequency, s.weekdays = "weekly", "2,4"  # Wed, Fri
    assert compute_next_run(s, datetime(2026, 10, 16, 4, 30), "Asia/Kolkata") == datetime(2026, 10, 21, 3, 30)
    s.frequency, s.day_of_month = "monthly", 1
    assert compute_next_run(s, datetime(2026, 10, 16, 4, 30), "Asia/Kolkata") == datetime(2026, 11, 1, 3, 30)
    s.frequency = "daily"  # DST: New York 09:00 is 13:00 UTC in summer, 14:00 in winter
    assert compute_next_run(s, datetime(2026, 7, 1, 0, 0), "America/New_York") == datetime(2026, 7, 1, 13, 0)
    assert compute_next_run(s, datetime(2026, 12, 1, 0, 0), "America/New_York") == datetime(2026, 12, 1, 14, 0)


def _schedule(client, ds, **extra):
    sp = client.post("/api/saved-pivots", json={
        "name": f"top {ds} {extra.pop('suffix', '')}",
        "config": _config(ds, valueFilters={"topN": {"by": "sum_N", "n": 2}})}).json()
    body = {"name": "Daily", "savedPivotId": sp["id"], "frequency": "daily", "runTime": "09:00",
            "to": "ops@example.com", "subject": "Top {rows} on {dataset}", "message": "Hello", **extra}
    res = client.post("/api/schedules", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def test_schedule_validation(client, upload):
    ds = upload(DATA)
    sp = client.post("/api/saved-pivots", json={"name": f"v {ds}", "config": _config(ds)}).json()
    base = {"name": "x", "savedPivotId": sp["id"], "to": "ops@example.com", "subject": "s"}
    assert client.post("/api/schedules", json={**base, "to": ""}).status_code == 400
    assert client.post("/api/schedules", json={**base, "to": "not-an-email"}).status_code == 400
    assert client.post("/api/schedules", json={**base, "runTime": "25:00"}).status_code == 400
    assert client.post("/api/schedules", json={**base, "frequency": "weekly", "weekdays": []}).status_code == 400
    assert client.post("/api/schedules", json={**base, "savedPivotId": 999999}).status_code == 400


def test_run_now_emails_top_rows(client, upload, fake_smtp):
    client.post("/api/email/smtp-settings", json=SMTP)
    ds = upload(DATA, name="ops.csv")
    sched = _schedule(client, ds)
    assert sched["nextRunAt"]

    res = client.post(f"/api/schedules/{sched['id']}/run").json()
    assert res["status"] == "success", res
    assert res["rowsSent"] == 2
    assert fake_smtp[-1]["subject"] == "Top 2 on ops.csv"
    attachment = next(p for p in fake_smtp[-1]["msg"].iter_attachments())
    assert attachment.get_filename().endswith(".xlsx")

    hist = client.get("/api/email/history").json()
    entry = next(h for h in hist if h["id"] == res["historyId"])
    assert entry["source"] == "schedule" and entry["scheduleId"] == sched["id"]
    assert entry["attachedRecordsCount"] == 5  # C (3 records) + A (2)


def test_run_due_claims_once_and_reschedules(client, upload, fake_smtp):
    from app.config.database import SessionLocal
    from app.models.report_schedule import ReportSchedule
    from app.services.scheduler_service import run_due

    client.post("/api/email/smtp-settings", json=SMTP)
    ds = upload(DATA)
    sched = _schedule(client, ds, suffix="due")
    db = SessionLocal()
    try:
        row = db.get(ReportSchedule, sched["id"])
        due = datetime.utcnow().replace(microsecond=0)
        row.next_run_at = due
        db.commit()
    finally:
        db.close()

    before = len(fake_smtp)
    assert run_due() >= 1
    assert run_due() == 0  # already claimed / rescheduled
    after = client.get(f"/api/schedules/{sched['id']}").json()
    assert after["lastStatus"] == "success"
    assert after["nextRunAt"] > due.isoformat()
    assert len(fake_smtp) == before + 1


def test_empty_pivot_is_skipped(client, upload, fake_smtp):
    client.post("/api/email/smtp-settings", json=SMTP)
    ds = upload(DATA)
    sp = client.post("/api/saved-pivots", json={"name": f"empty {ds}", "config": _config(
        ds, valueFilters={"conditions": [{"by": "sum_N", "op": "gt", "value": 1000}]})}).json()
    sched = client.post("/api/schedules", json={"name": "e", "savedPivotId": sp["id"],
                                                "to": "ops@example.com", "subject": "s"}).json()
    before = len(fake_smtp)
    res = client.post(f"/api/schedules/{sched['id']}/run").json()
    assert res["status"] == "skipped" and len(fake_smtp) == before


def test_failed_send_is_recorded(client, upload, monkeypatch):
    client.post("/api/email/smtp-settings", json=SMTP)

    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(smtplib, "SMTP", boom)
    ds = upload(DATA)
    sched = _schedule(client, ds, suffix="fail")
    res = client.post(f"/api/schedules/{sched['id']}/run").json()
    assert res["status"] == "failed" and "connection refused" in res["error"]
    assert client.get(f"/api/schedules/{sched['id']}").json()["lastStatus"] == "failed"
