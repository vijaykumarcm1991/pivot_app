"""Regression tests for the non-pivot backend fixes."""
import os
from datetime import datetime

import pandas as pd


def test_iana_timezones_are_honoured():
    from app.utils.tz import format_ist

    dt = datetime(2026, 7, 1, 12, 0, 0)  # naive UTC
    assert format_ist(dt, fmt="%H:%M", tz_name="Asia/Singapore") == "20:00"
    assert format_ist(dt, fmt="%H:%M", tz_name="America/New_York") == "08:00"  # EDT
    assert format_ist(dt, fmt="%H:%M", tz_name="Asia/Kolkata") == "17:30"
    assert format_ist(dt, fmt="%H:%M", tz_name="+02:00") == "14:00"


def test_email_cells_never_render_none():
    from app.services.email_service import _pivot_rows_to_html

    html = _pivot_rows_to_html(
        [{"Region": "North", "avg": None, "count": 3.0}],
        {"columns": ["Region", "avg", "count"]},
    )
    assert "None" not in html
    assert ">3<" in html


def test_dataset_delete_removes_rows_and_file(client, upload):
    from app.config.settings import UPLOAD_DIR

    ds = upload(pd.DataFrame({"A": ["x", "y"]}))
    stored = client.get(f"/api/dataset/{ds}").json()["stored_filename"]
    assert os.path.exists(os.path.join(UPLOAD_DIR, stored))
    res = client.delete(f"/api/dataset/{ds}")
    assert res.status_code == 200, res.text
    assert client.get(f"/api/dataset/{ds}").status_code == 404
    assert not os.path.exists(os.path.join(UPLOAD_DIR, stored))


def test_upload_over_limit_returns_json_413(client):
    client.post("/api/settings", json={"maxUploadBytes": 1024 * 1024})
    try:
        big = b"A,B\n" + b"1,2\n" * 400_000  # ~1.6 MB
        res = client.post("/api/upload", files={"file": ("big.csv", big, "text/csv")})
        assert res.status_code == 413
        assert "maximum allowed size" in res.json()["detail"]
    finally:
        client.post("/api/settings", json={"maxUploadBytes": 50 * 1024 * 1024})


def test_upload_size_setting_is_capped_at_nginx_limit(client):
    from app.config.settings import MAX_UPLOAD_CEILING_BYTES

    res = client.post("/api/settings", json={"maxUploadBytes": 10 * 1024 ** 3})
    assert res.json()["maxUploadBytes"] == MAX_UPLOAD_CEILING_BYTES
    client.post("/api/settings", json={"maxUploadBytes": 50 * 1024 * 1024})


def test_api_404_keeps_detail(client):
    res = client.get("/api/dataset/999999")
    assert res.status_code == 404
    assert res.json()["detail"] == "Dataset not found"


def test_user_directory_bom_and_bad_file(tmp_path, monkeypatch):
    from app.services import user_directory as ud

    users = tmp_path / "Users.csv"
    users.write_bytes(
        b'\xef\xbb\xbf"PrimarySmtpAddress","DisplayName","Alias"\r\n'
        b'"ann@example.com","Ann Lee","ann"\r\n'
    )
    monkeypatch.setenv("USERS_CSV_PATH", str(users))
    monkeypatch.setenv("DISTRIBUTION_LISTS_CSV_PATH", str(tmp_path / "missing.csv"))
    ud.initial_load()
    try:
        assert [r["email"] for r in ud.search("ann")] == ["ann@example.com"]
        assert ud.status()["lastError"] is None  # missing DL file is not an error

        users.write_bytes(b"\xff\xfe\x00bad")  # undecodable
        os.utime(users, (1, 1))
        ud.search("ann")
        calls = []
        real = ud._load_csv
        monkeypatch.setattr(ud, "_load_csv", lambda *a: calls.append(a) or real(*a))
        ud.search("ann")
        ud.search("ann")
        assert calls == []  # a broken file is not re-read on every request
    finally:
        monkeypatch.undo()
        ud.initial_load()
