"""Regression tests for the pivot engine, selections and soft delete."""
import numpy as np
import pandas as pd


def _pivot(client, ds, **kw):
    body = {"datasetId": ds, "sheetName": "Sheet1", **kw}
    res = client.post("/api/pivot", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _data_rows(resp):
    return [
        r for r in resp["rows"]
        if "_warning" not in r and not r.get("__isSubtotal") and not r.get("__isColumnTotal")
    ]


def _dry_run(client, pivot_request, selections):
    res = client.post("/api/pivot/delete-records", json={
        "pivotRequest": pivot_request, "selections": selections, "dryRun": True,
    })
    return res


SALES = pd.DataFrame({
    "Region": ["North", "North", "North", "South", "South", None],
    "Product": ["A", "B", "A", "A", "B", "A"],
    "Status": ["Open", "Closed", "Open", "Open", "Open", "Closed"],
    "Amount": [10, 20, 30, 40, 50, 60],
    "Date": ["2026-01-05", "2026-01-20", "2026-02-03", "2026-02-10", "2026-03-01", "2026-03-15"],
})


def test_compact_layout_rows_carry_row_fields_and_select_precisely(client, upload):
    ds = upload(SALES)
    req = {"rows": ["Region", "Product"], "values": [{"field": "Amount", "aggregation": "sum", "label": "sum_Amount"}],
           "layout": "compact"}
    resp = _pivot(client, ds, **req)
    north_a = next(r for r in _data_rows(resp) if r["Rows"] == "North / A")
    assert north_a["__rowFields"] == {"Region": "North", "Product": "A"}

    pr = {"datasetId": ds, "sheetName": "Sheet1", **req}
    res = _dry_run(client, pr, [north_a["__rowFields"]])
    assert res.status_code == 200, res.text
    assert res.json()["matched"] == 2  # not the whole dataset


def test_empty_selection_never_matches_everything(client, upload):
    ds = upload(SALES)
    pr = {"datasetId": ds, "sheetName": "Sheet1", "rows": ["Region"], "values": []}
    res = _dry_run(client, pr, [{}])
    assert res.status_code == 400
    dd = client.post("/api/pivot/drilldown", json={**pr, "selection": {}})
    assert dd.json()["metadata"]["matched_rows"] == 0


def test_unknown_selection_field_is_rejected(client, upload):
    ds = upload(SALES)
    pr = {"datasetId": ds, "sheetName": "Sheet1", "rows": ["Region"], "values": []}
    res = _dry_run(client, pr, [{"NotAColumn": "x"}])
    assert res.status_code == 400


def test_blank_row_value_can_be_drilled_and_filtered(client, upload):
    ds = upload(SALES)
    pr = {"datasetId": ds, "sheetName": "Sheet1", "rows": ["Region"], "values": []}
    resp = _pivot(client, ds, rows=["Region"], values=[])
    blank = next(r for r in _data_rows(resp) if r["Region"] == "(blank)")
    dd = client.post("/api/pivot/drilldown", json={**pr, "selection": blank["__rowFields"]})
    assert dd.json()["metadata"]["matched_rows"] == 1

    filtered = _pivot(client, ds, rows=["Product"], values=[], filters={"Region": [None]})
    assert filtered["metadata"]["filtered_rows"] == 1


def test_delete_has_no_5000_row_cap(client, upload):
    n = 6200
    df = pd.DataFrame({"Cat": ["big"] * n + ["small"] * 3, "Id": range(n + 3)})
    ds = upload(df)
    pr = {"datasetId": ds, "sheetName": "Sheet1", "rows": ["Cat"], "values": []}
    assert _dry_run(client, pr, [{"Cat": "big"}]).json()["matched"] == n
    res = client.post("/api/pivot/delete-records", json={"pivotRequest": pr, "selections": [{"Cat": "big"}]})
    body = res.json()
    assert res.status_code == 200, res.text
    assert body["deleted"] == n
    after = _pivot(client, ds, rows=["Cat"], values=[])
    assert [r["Cat"] for r in _data_rows(after)] == ["small"]


def test_soft_delete_sticks_for_all_numeric_sheet(client, upload):
    df = pd.DataFrame({"Code": [1, 2, 2, 3], "Score": [1.5, 2.5, 3.5, np.nan]})
    ds = upload(df)
    pr = {"datasetId": ds, "sheetName": "Sheet1", "rows": ["Code"],
          "values": [{"field": "Score", "aggregation": "sum", "label": "sum_Score"}]}
    res = client.post("/api/pivot/delete-records", json={"pivotRequest": pr, "selections": [{"Code": 2}]})
    assert res.json()["deleted"] == 2
    after = _pivot(client, ds, **{k: v for k, v in pr.items() if k not in {"datasetId", "sheetName"}})
    assert [r["Code"] for r in _data_rows(after)] == [1, 3]


def test_dry_run_counts_overlapping_selections_once(client, upload):
    ds = upload(SALES)
    pr = {"datasetId": ds, "sheetName": "Sheet1", "rows": ["Region"], "values": []}
    res = _dry_run(client, pr, [{"Region": "North"}, {"Region": "North"}])
    assert res.json()["matched"] == 3


def test_float_row_field_matches_json_integer(client, upload):
    df = pd.DataFrame({"Year": [2024.0, 2025.0, np.nan], "V": [1, 2, 3]})
    ds = upload(df)
    pr = {"datasetId": ds, "sheetName": "Sheet1", "rows": ["Year"], "values": []}
    assert _dry_run(client, pr, [{"Year": 2024}]).json()["matched"] == 1


def test_subtotals_with_date_grouping_are_per_group(client, upload):
    ds = upload(SALES)
    resp = _pivot(
        client, ds,
        rows=["Date", "Product"], dateGrouping={"Date": "month"},
        values=[{"field": "Amount", "aggregation": "sum", "label": "sum_Amount"}],
        totals={"showSubtotals": True},
    )
    subs = [r for r in resp["rows"] if r.get("__isSubtotal")]
    assert {s["Date_month"]: s["sum_Amount"] for s in subs} == {"2026-01": 30, "2026-02": 70, "2026-03": 110}
    assert not any(k.startswith("__pivot_") for r in resp["rows"] for k in r)
    leaf = _data_rows(resp)[0]
    assert leaf["__level"] == 1 and leaf["__parentKey"] == "2026-01"
    assert subs[0]["__groupKey"] == "2026-01"


def test_subtotals_and_column_totals_with_column_field(client, upload):
    ds = upload(SALES)
    resp = _pivot(
        client, ds,
        rows=["Region", "Product"], columns=["Status"],
        values=[{"field": "Amount", "aggregation": "sum", "label": "sum_Amount"}],
        totals={"showSubtotals": True, "showColumnTotals": True},
    )
    assert "sum_Amount | Open" in resp["columns"]
    north_sub = next(r for r in resp["rows"] if r.get("__isSubtotal") and r["Region"] == "North")
    assert north_sub["sum_Amount | Open"] == 40
    assert north_sub["sum_Amount | Closed"] == 20
    assert north_sub["row_total"] == 60
    col_total = next(r for r in resp["rows"] if r.get("__isColumnTotal"))
    assert col_total["sum_Amount | Open"] == 130
    assert col_total["row_total"] == 210


def test_average_subtotal_is_weighted_and_missing_cells_are_null(client, upload):
    ds = upload(SALES)
    resp = _pivot(
        client, ds,
        rows=["Region", "Product"], columns=["Status"],
        values=[{"field": "Amount", "aggregation": "average", "label": "average_Amount"}],
        totals={"showSubtotals": True},
    )
    north_sub = next(r for r in resp["rows"] if r.get("__isSubtotal") and r["Region"] == "North")
    # North records: 10, 20, 30 → average 20 (not the mean of per-product averages)
    assert north_sub["row_total"] == 20
    south_a = next(r for r in _data_rows(resp) if r["Region"] == "South" and r["Product"] == "A")
    assert south_a["average_Amount | Closed"] is None


def test_compact_subtotals(client, upload):
    ds = upload(SALES)
    resp = _pivot(
        client, ds, rows=["Region", "Product"], layout="compact",
        values=[{"field": "Amount", "aggregation": "count", "label": "count_Amount"}],
        totals={"showSubtotals": True},
    )
    subs = [r for r in resp["rows"] if r.get("__isSubtotal")]
    assert {s["Rows"]: s["count_Amount"] for s in subs}["North Total"] == 3


def test_row_totals_toggle_removes_column(client, upload):
    ds = upload(SALES)
    resp = _pivot(
        client, ds, rows=["Region"], columns=["Status"],
        values=[{"field": "Amount", "aggregation": "sum", "label": "sum_Amount"}],
        totals={"showRowTotals": False},
    )
    assert "row_total" not in resp["columns"]
    assert all("row_total" not in r for r in resp["rows"])


def test_email_attachment_counts_distinct_records(client, upload):
    from app.services.pivot_service import build_drilldown_multi
    from app.config.database import SessionLocal

    ds = upload(SALES)
    db = SessionLocal()
    try:
        out = build_drilldown_multi(
            db, ds, "Sheet1", ["Region"], [], [], {}, {}, {}, {}, "tabular",
            [{"Region": "North"}, {"Region": "North"}, {"Region": "South"}], limit=100000,
        )
    finally:
        db.close()
    assert out["metadata"]["matched_rows"] == 5
    assert len(out["rows"]) == 5


def test_filter_values_endpoint_numeric_header_and_soft_deletes(client, upload):
    df = pd.DataFrame({"2024": ["a", "b", "c"], "K": [1, 2, 3]})
    ds = upload(df)
    res = client.get(f"/api/dataset/{ds}/sheet/Sheet1/field/2024/values")
    assert res.status_code == 200, res.text
    assert sorted(res.json()["values"]) == ["a", "b", "c"]

    pr = {"datasetId": ds, "sheetName": "Sheet1", "rows": ["2024"], "values": []}
    client.post("/api/pivot/delete-records", json={"pivotRequest": pr, "selections": [{"2024": "b"}]})
    res = client.get(f"/api/dataset/{ds}/sheet/Sheet1/field/2024/values")
    assert sorted(res.json()["values"]) == ["a", "c"]


def test_grand_totals_cover_column_groups(client, upload):
    ds = upload(SALES)
    resp = _pivot(
        client, ds, rows=["Region"], columns=["Status"],
        values=[{"field": "Amount", "aggregation": "sum", "label": "sum_Amount"}],
    )
    grand = resp["totals"]["grand"]
    assert grand["sum_Amount | Open"] == 130
    assert grand["sum_Amount | Closed"] == 80
    assert grand["row_total"] == 210


def test_html_404_page_renders(client):
    res = client.get("/no-such-page")
    assert res.status_code == 404
    assert "Page not found" in res.text


ALERTS = pd.DataFrame({
    "Cat": ["A"] * 5 + ["B"] * 3 + ["C"] * 8 + ["D"] * 1 + [None] * 2,
    "Unit": (["X", "Y"] * 10)[:19],
    "N": [1] * 19,
})


def test_top_n_keeps_highest_groups_ranked_and_totals_follow(client, upload):
    ds = upload(ALERTS)
    resp = _pivot(
        client, ds, rows=["Cat"],
        values=[{"field": "N", "aggregation": "sum", "label": "sum_N"}],
        valueFilters={"topN": {"by": "sum_N", "n": 2, "direction": "top"}},
    )
    assert [(r["Cat"], r["sum_N"]) for r in _data_rows(resp)] == [("C", 8), ("A", 5)]
    assert resp["totals"]["grand"]["sum_N"] == 13
    assert resp["metadata"]["filtered_rows"] == 13


def test_bottom_n_and_thresholds(client, upload):
    ds = upload(ALERTS)
    vals = [{"field": "N", "aggregation": "count", "label": "count_N"}]
    bottom = _pivot(client, ds, rows=["Cat"], values=vals,
                    valueFilters={"topN": {"by": "count_N", "n": 2, "direction": "bottom"}})
    assert [r["Cat"] for r in _data_rows(bottom)] == ["D", "(blank)"]

    thr = _pivot(client, ds, rows=["Cat"], values=vals,
                 valueFilters={"conditions": [{"by": "count_N", "op": "gte", "value": 3},
                                              {"by": "count_N", "op": "lt", "value": 8}]})
    assert sorted(r["Cat"] for r in _data_rows(thr)) == ["A", "B"]


def test_top_n_with_column_groups_ranks_by_row_total(client, upload):
    ds = upload(ALERTS)
    resp = _pivot(client, ds, rows=["Cat"], columns=["Unit"],
                  values=[{"field": "N", "aggregation": "sum", "label": "sum_N"}],
                  valueFilters={"topN": {"by": "sum_N", "n": 1}})
    rows = _data_rows(resp)
    assert len(rows) == 1 and rows[0]["Cat"] == "C" and rows[0]["row_total"] == 8


def test_value_filter_unknown_label_is_400(client, upload):
    ds = upload(ALERTS)
    res = client.post("/api/pivot", json={"datasetId": ds, "sheetName": "Sheet1", "rows": ["Cat"],
                                          "valueFilters": {"topN": {"by": "nope", "n": 3}}})
    assert res.status_code == 400
    assert "Value filter field not found" in res.json()["detail"]
