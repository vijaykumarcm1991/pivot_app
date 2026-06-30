# Pivot Configuration Contract — Code Review

> **Note on filenames.** The review prompt asked for `pivot_builder.html` and
> `pivot-builder.js`. In the actual repository those files are
> `backend/app/templates/pivot.html` and
> `backend/app/static/js/pivot.js`. Everything below is taken from the real
> files, line numbers, and live code paths, not an example.
>
> Reviewed commit: `f782c81` (current `main`).
> Phase: **3 — Pivot Builder**. The compute pipeline is shipped; the export /
> save / drilldown buttons are placeholders for Phases 4–5.

---

## 1. Where the contract lives

| Layer            | File                                                      | Lines  | Role                                            |
|------------------|-----------------------------------------------------------|--------|-------------------------------------------------|
| UI template      | `backend/app/templates/pivot.html`                        | 321    | Renders the Pivot Builder page                  |
| UI controller    | `backend/app/static/js/pivot.js`                          | 837    | Builds the payload and calls the API            |
| Page route       | `backend/app/routes/pivot_routes.py`                      | 69     | `GET /pivot`                                    |
| API: validate    | `backend/app/routes/pivot_routes.py` (`api_pivot_validate`) | 40–49 | `POST /api/pivot/validate`                      |
| API: compute     | `backend/app/routes/pivot_routes.py` (`api_pivot`)        | 52–58  | `POST /api/pivot`                               |
| API: drilldown   | `backend/app/routes/pivot_routes.py` (`api_pivot_drilldown`) | 61–69 | `POST /api/pivot/drilldown`                     |
| Request schema   | `backend/app/schemas/pivot.py`                            | 90     | Pydantic `PivotRequest` + `PivotValue` + `TotalsOptions` |
| Validation logic | `backend/app/services/pivot_validation_service.py`        | 271    | Pure-metadata check, no file IO                 |
| Engine           | `backend/app/services/pivot_service.py`                   | 599    | Pandas pivot, honours filters, grouping, sort, totals |
| Settings         | `backend/app/config/settings.py`                          | 32     | Size limits and constants                       |

`pivot.js` calls `fetch("/api/datasets")`, `/api/dataset/{id}`,
`/api/dataset/{id}/sheet/{name}/columns`,
`/api/dataset/{id}/sheet/{name}/preview` first (Phase 2 metadata), then
posts the configured payload to `/api/pivot/validate` and `/api/pivot`.

---

## 2. Endpoint summary

| Action            | Method | URL                          | Returns                  | Notes                                                                 |
|-------------------|--------|------------------------------|--------------------------|-----------------------------------------------------------------------|
| Render page       | GET    | `/pivot`                     | `pivot.html`             | Server-rendered. No JSON.                                             |
| Validate config   | POST   | `/api/pivot/validate`        | `PivotValidateResponse`  | **Does not load the file.** Pure metadata check.                      |
| Compute pivot     | POST   | `/api/pivot`                 | `PivotResponse`          | Loads the sheet, applies filters, computes pandas pivot.              |
| Drill-down        | POST   | `/api/pivot/drilldown`       | `PivotDrilldownResponse` | Returns raw rows that match a pivot cell selection (max 5000).        |

All `POST` endpoints expect `Content-Type: application/json` and accept
`populate_by_name=True`, so both camelCase and snake_case keys are valid
in the request body. The frontend always sends camelCase.

---

## 3. The complete request body

This is the literal object returned by `buildPayload()` in
`backend/app/static/js/pivot.js` (lines 643–656). It is the exact value that
hits `POST /api/pivot/validate` and `POST /api/pivot` when the user clicks
**Validate** or **Compute Pivot**.

```json
{
  "datasetId": 1,
  "sheetName": "Sales",
  "rows": ["Region", "OrderDate"],
  "columns": ["Status"],
  "values": [
    { "field": "Amount", "aggregation": "sum",     "label": "sum_Amount"     },
    { "field": "Amount", "aggregation": "average", "label": "average_Amount" }
  ],
  "filters": {
    "Region": ["North", "South"],
    "Status": ["Open",   "Closed"]
  },
  "dateGrouping": {
    "OrderDate": "month"
  },
  "sorting": {
    "Region": "asc"
  },
  "totals": {
    "showGrandTotals":  true,
    "showRowTotals":    true,
    "showColumnTotals": false,
    "showSubtotals":    false
  },
  "layout": "tabular"
}
```

### 3.1 Field-by-field description

| Field           | Type                          | Required | Default (applied by Pydantic when omitted) | Source of truth                       |
|-----------------|-------------------------------|----------|--------------------------------------------|---------------------------------------|
| `datasetId`     | int                           | **Yes**  | –                                          | `PivotRequest.dataset_id`             |
| `sheetName`     | string                        | **Yes**  | –                                          | `PivotRequest.sheet_name`             |
| `rows`          | `string[]`                    | No       | `[]`                                       | `PivotRequest.rows`                   |
| `columns`       | `string[]`                    | No       | `[]`                                       | `PivotRequest.columns`                |
| `values`        | `string[]` **or** `PivotValue[]` | No       | engine auto-injects `count(<first col>)`   | `PivotRequest.values`                 |
| `filters`       | `{ field: value }`            | No       | `{}`                                       | `PivotRequest.filters`                |
| `dateGrouping`  | `{ field: "year"\|"quarter"\|"month"\|"week"\|"day" }` | No | `{}`                                | `PivotRequest.date_grouping`          |
| `sorting`       | `{ field: "asc"\|"desc" }`    | No       | `{}`                                       | `PivotRequest.sorting`                |
| `totals`        | `TotalsOptions` (see below)   | No       | see TotalsOptions defaults                 | `PivotRequest.totals`                 |
| `layout`        | `"tabular"` \| `"compact"`    | No       | `"tabular"`                                | `PivotRequest.layout`                 |

### 3.2 `PivotValue` (inside `values`)

| Key            | Type   | Required | Default | Notes                                                     |
|----------------|--------|----------|---------|-----------------------------------------------------------|
| `field`        | string | **Yes**  | –       | Must exist on the sheet.                                  |
| `aggregation`  | string | No       | `"sum"` | One of: `count`, `sum`, `average`, `min`, `max` (case-insensitive; lowercased before use). |
| `label`        | string | No       | `null`  | If null, the engine uses `"<aggregation>_<field>"`.       |

`values` may also be a plain `string[]` of field names. In that case the
schema coerces each entry to `PivotValue(field=x, aggregation="sum")`
(see `_coerce_value()` in `pivot_validation_service.py:247`).

### 3.3 `TotalsOptions`

| Key                | Type | Default | Description                                       |
|--------------------|------|---------|---------------------------------------------------|
| `showGrandTotals`  | bool | `true`  | Add a `totals.grand` object to the response.      |
| `showRowTotals`    | bool | `true`  | Add a `row_total` column per pivot row.           |
| `showColumnTotals` | bool | `false` | Reserved for Phase 4; engine no-ops this branch.  |
| `showSubtotals`    | bool | `false` | Reserved for Phase 4; engine no-ops this branch.  |

Pydantic accepts both camelCase (`showGrandTotals`) and snake_case
(`show_grand_totals`) — see `populate_by_name=True` in
`schemas/pivot.py:25`.

### 3.4 `filters` value shapes

`pivot_service._apply_filters` (lines 240–255) and
`_apply_structured_filter` (lines 258–280) define three forms the value
can take:

| Form                       | Meaning                                          | Example                       |
|----------------------------|--------------------------------------------------|-------------------------------|
| Scalar                     | `field == value`                                 | `"Status": "Open"`            |
| Array                      | `field.isin([...])`                              | `"Status": ["Open","Closed"]` |
| `null`                     | Keep rows where `field` is `NaN`/`null`          | `"Region": null`              |
| Object `{in, notIn, equals, contains, from, to}` | Advanced (Phase 4-ready) | `"OrderDate": { "from": "2024-01-01" }` |

The Pivot Builder UI currently emits only the **scalar**, **array** and
**null** forms via the filter modal (`pivot.js:583–595`); the structured
form is already accepted by the engine for the drilldown / future use.

---

## 4. Validation rules (every rule the backend enforces)

These come straight from `pivot_validation_service.validate_pivot()`
(`pivot_validation_service.py:65–240`). Rules run in this order; the
function returns as soon as a dataset / sheet is missing.

| # | Rule                                                                                                       | Severity |
|---|------------------------------------------------------------------------------------------------------------|----------|
| 1 | `datasetId` must resolve to a row in the `datasets` table.                                                 | Error    |
| 2 | `layout` must be in `{"compact", "tabular"}`.                                                              | Error    |
| 3 | `sheetName` must exist for that dataset.                                                                   | Error    |
| 4 | Every field in `rows`, `columns`, `filters`, `dateGrouping`, `sorting` must exist in the sheet's columns.   | Error    |
| 5 | Every `value.field` must exist in the sheet.                                                               | Error    |
| 6 | `value.aggregation` must be one of `count`, `sum`, `average`, `min`, `max` (case-insensitive).             | Error    |
| 7 | Aggregation must be allowed for the field's data type (see matrix below).                                  | Error    |
| 8 | `dateGrouping[*]` must be one of `year`, `quarter`, `month`, `week`, `day`.                                | Error    |
| 9 | If a date grouping is set on a non-date column, a warning is emitted (not an error).                       | Warning  |
| 10 | Sheet row count > `MAX_ROWS_ALLOWED` (100 000) → warning.                                                 | Warning  |
| 11 | Column count > `MAX_COLUMNS_ALLOWED` (200) → warning.                                                     | Warning  |
| 12 | `sorting[*]` direction must be `asc`/`desc` (or `ascending`/`descending`).                                 | Error    |
| 13 | `values` empty → engine auto-injects `count(<first column>)`; backend adds a **warning**.                  | Warning  |

### 4.1 Aggregation × data type matrix

From `valid_aggregations_for()` in
`pivot_validation_service.py:52–58`. Mirrored in `AGG_BY_TYPE` in
`pivot.js:54–63` so the UI dropdown only offers valid options.

| Data type (UI / internal)  | Text / Boolean (string, text, boolean) | Numeric (integer, float, decimal) | Date (datetime, date) |
|----------------------------|---------------------------------------|-----------------------------------|-----------------------|
| `count`                    | ✓                                     | ✓                                 | ✓                     |
| `sum`                      | –                                     | ✓                                 | ✓                     |
| `average`                  | –                                     | ✓                                 | ✓                     |
| `min`                      | –                                     | ✓                                 | ✓                     |
| `max`                      | –                                     | ✓                                 | ✓                     |

The internal vocabulary in the codebase is:

| Internal    | UI label on this app          | Notes                                                   |
|-------------|-------------------------------|---------------------------------------------------------|
| `string`    | Text                          | non-numeric, non-date, non-bool                         |
| `integer`   | Integer                       | whole numbers                                           |
| `float`     | Decimal                       | floats (incl. Excel roundtrip 0/1 unless all 0/1)       |
| `decimal`   | Decimal                       | alias for `float`                                       |
| `boolean`   | Boolean                       | True/False **or** float 0.0/1.0-only                    |
| `datetime`  | Date                          | pandas-parseable timestamp                              |
| `date`      | Date                          | alias for `datetime`                                    |

---

## 5. Enums — every supported value

| Enum              | Allowed values                                  | Source                                            |
|-------------------|-------------------------------------------------|---------------------------------------------------|
| `aggregation`     | `count`, `sum`, `average`, `min`, `max`         | `pivot_service.AGGREGATIONS` (line 33)            |
| `dateGrouping[*]` | `year`, `quarter`, `month`, `week`, `day`       | `pivot_service.DATE_GROUPS` (line 42)             |
| `layout`          | `compact`, `tabular`                            | `pivot_service._validate_layout` (line 75)        |
| `sorting[*]`      | `asc`, `desc` (also tolerates `ascending`/`descending`) | `pivot_validation_service.py:228`        |
| `totals.*`        | boolean (true / false)                          | `schemas/pivot.TotalsOptions`                     |

Layout semantics in the engine
(`pivot_service._compute_pivot_rows`, lines 386–398):

* **tabular** — each row field becomes its own column.
* **compact** — when there is more than one row field, they are merged
  into a single `Rows` column whose value is `"a / b / c"`.

---

## 6. Response bodies

### 6.1 `POST /api/pivot/validate` — `PivotValidateResponse`

Returned by `pivot_validation_service.py:_build_response`
(lines 258–271). The frontend renders it inside the *Validation* card and
the *debug* JSON panel.

```json
{
  "valid": true,
  "errors": [],
  "warnings": [],
  "summary": {
    "dataset":       "sales-2024.xlsx",
    "sheet":         "Sales",
    "rows":          ["Region", "OrderDate"],
    "columns":       ["Status"],
    "values": [
      { "field": "Amount", "aggregation": "sum",     "label": "sum_Amount"     },
      { "field": "Amount", "aggregation": "average", "label": "average_Amount" }
    ],
    "filters":       { "Region": ["North","South"], "Status": ["Open","Closed"] },
    "date_grouping": { "OrderDate": "month" },
    "layout":        "tabular"
  },
  "per_value_field": {
    "Amount": {
      "data_type": "float",
      "allowed_aggregations": ["count", "sum", "average", "min", "max"]
    }
  }
}
```

When `valid` is `false`, the response is still 200 OK and the frontend
treats the errors as a blocking banner. Errors are strings, one per rule.

### 6.2 `POST /api/pivot` — `PivotResponse`

Built by `pivot_service.build_pivot()` (lines 80–146).

```json
{
  "rows": [
    { "Region": "North", "OrderDate_month": "2024-01", "sum_Amount": 12345.67, "row_total": 12345.67 }
  ],
  "columns": ["Region", "OrderDate_month", "sum_Amount", "row_total"],
  "totals": {
    "grand": { "sum_Amount": 54321.09, "average_Amount": 678.45 },
    "row_total_field": "row_total"
  },
  "metadata": {
    "dataset_id":     1,
    "sheet_name":     "Sales",
    "source_rows":    12000,
    "filtered_rows":  8410,
    "layout":         "tabular",
    "rows":           ["Region", "OrderDate"],
    "columns":        ["Status"],
    "date_grouping":  { "OrderDate": "month" },
    "sorting":        { "Region": "asc" },
    "totals":         { "showGrandTotals": true, "showRowTotals": true, "showColumnTotals": false, "showSubtotals": false }
  },
  "aggregations": [
    { "field": "Amount", "aggregation": "sum",     "label": "sum_Amount"     },
    { "field": "Amount", "aggregation": "average", "label": "average_Amount" }
  ]
}
```

Notes:

* Date-grouped columns appear as `<Field>_<grouping>`, e.g. `OrderDate_month`.
* If the pivot has more than `MAX_PIVOT_RESULT_ROWS` (10 000) rows, the
  engine truncates and prepends a sentinel
  `{"_warning": "Only showing first 10,000 of N rows…"}` row
  (`pivot_service.py:379–384`).
* The frontend (`pivot.js:752–787`) maps `data.columns` to AG Grid
  `columnDefs` and `data.rows` to `rowData`. The metadata goes into the
  header (`metaStats`).

### 6.3 `POST /api/pivot/drilldown` — `PivotDrilldownResponse`

```json
{
  "rows":     [ { "OrderID": "SO-1001", "Amount": 99.50, ... } ],
  "columns":  ["OrderID", "Amount", "..."],
  "metadata": {
    "dataset_id":    1,
    "sheet_name":    "Sales",
    "matched_rows":  142,
    "returned_rows": 142,
    "limit":         500,
    "selection":     { "Region": "North", "OrderDate_month": "2024-01" }
  }
}
```

Cap is `min(request.limit, 5000)` (`pivot_service.py:158`).

---

## 7. End-to-end request flow (one click)

```
1. User clicks "Compute Pivot"
        ↓
2. computePivot() in pivot.js (lines 712–749)
        ↓
3. buildPayload() (lines 643–656) — object above
        ↓
4. fetch("/api/pivot", { method:"POST", body: JSON.stringify(payload) })
        ↓
5. FastAPI binds body to PivotRequest (Pydantic, populate_by_name=True)
        ↓
6. api_pivot() → build_pivot() in pivot_service.py
        ↓
7. Engine: load sheet → normalise values → prepare group fields
        → apply filters → pandas.pivot_table → rename
        → sort → totals
        ↓
8. PivotResponse returned to pivot.js → renderPivotGrid() → AG Grid
```

The exact `requestJson` shown in the UI debug card is the same object
sent in step 4.

---

## 8. How the engine will use this JSON in the next phase

The Phase 4 engine contract is the **same** `PivotRequest`. The only
differences will be the response and downstream consumers.

1. **Load the sheet** from `datasetId` / `sheetName` (already happens;
   `_load_dataset_sheet`, `pivot_service.py:174`).
2. **Filter** with `_apply_filters()` (lines 240–255). Phase 4 will
   surface the warning "filters reduced N → M rows" using
   `metadata.filtered_rows` (already in the response).
3. **Date-group** any field whose name appears as a key in
   `dateGrouping`. The engine creates a helper column
   `__pivot_<field>_<grouping>` (`_date_group_field`, line 480), replaces
   it in the grouping index, and renames it back to
   `<field>_<grouping>` for display (`_rename_group_columns`,
   line 495).
4. **Build the pivot** via `pandas.pivot_table` keyed by `rows` (index)
   × `columns` (columns) and the aggregations from `values`
   (`_compute_pivot_rows`, lines 283–398).
5. **Sort** by every entry in `sorting` whose key is in `rows`. The
   engine applies `pivot_df.sort_values()` after the pivot is built
   because `pivot_table` reorders the index (lines 361–374).
6. **Totals**:
   * `showGrandTotals` → `totals.grand` (line 413).
   * `showRowTotals` → `row_total` per row (line 423).
   * `showColumnTotals` and `showSubtotals` are read by the engine but
     not yet rendered; Phase 4 will honour them.
7. **Layout** controls the row-column shape:
   * `tabular` — one column per row field.
   * `compact` — multiple row fields combined into a single `Rows`
     column with values `"a / b / c"` (lines 386–393).
8. **Drilldown** (`/api/pivot/drilldown`): same payload plus `selection`
   and `limit`. The engine returns up to 5000 raw rows that match the
   pivot cell the user clicked.
9. **Export** (Phase 4 button `exportBtn` — currently a stub at
   `pivot.js:812`) will reuse the same `buildPayload()` and call a new
   `/api/pivot/export` that returns an `.xlsx` file. The contract is
   already complete; only the route is missing.
10. **Save config** (Phase 5 button `saveBtn` — stub at
    `pivot.js:813`) will persist the same object under a
    `saved_pivots` table and re-load it on page open. The payload is
    already JSON-serialisable and contains everything needed to
    reproduce the pivot.

---

## 9. Frontend / backend / schema alignment check

| Concern                          | Frontend (`pivot.js`)                                       | Schema (`schemas/pivot.py`)              | Engine / Validation                                  | Aligned |
|----------------------------------|-------------------------------------------------------------|------------------------------------------|------------------------------------------------------|---------|
| Top-level keys                   | camelCase from `buildPayload()`                             | `alias=` + `populate_by_name=True`       | reads `request.<attr>` directly                      | ✅       |
| `datasetId` required             | guarded by `canSubmit` before enabling buttons              | `int` (no default)                        | error if missing                                     | ✅       |
| `sheetName` required             | guarded by `canSubmit`                                      | `str` (no default)                        | error if missing                                     | ✅       |
| Default `layout`                 | `"tabular"` in `appState`                                   | `layout: str = "tabular"`                | `_validate_layout` allows both                       | ✅       |
| Default `totals`                 | explicit object in `appState`                               | `TotalsOptions()` with documented defaults | honoured in `_compute_totals`                        | ✅       |
| `values` accept bare strings     | always objects (UI builds objects)                          | accepts `str` or `PivotValue`            | `_coerce_value` normalises both                      | ✅       |
| Aggregation per data type        | `AGG_BY_TYPE` mirrors `valid_aggregations_for`              | not enforced here                         | `valid_aggregations_for()` is the authority          | ✅       |
| Date grouping enum               | dropdown in `pivot.html:104-110`                            | free-form `Dict[str, str]`               | `DATE_GROUPS = {year,quarter,month,week,day}`        | ✅       |
| Sort direction enum              | buttons: `asc` / `desc` / `""`                              | free-form `Dict[str, str]`               | accepts `asc`, `desc`, `ascending`, `descending`     | ✅       |
| Filter value shape               | `string[]` or absent                                        | `Dict[str, Any]`                         | `list` / scalar / null / structured                  | ✅       |

The contract is internally consistent. Every field the UI writes is
read by the same name on the backend.

---

## 10. Caveats / known gaps before Phase 4

1. **`showColumnTotals` and `showSubtotals`** are stored and round-trip
   in metadata but the engine does not yet render them. The schema,
   defaults and validation already accept them.
2. **Distinct filter values** are derived from the first 100 preview
   rows (`pivot.js:516–527`) — a dedicated `/api/dataset/.../distinct`
   endpoint would scale better.
3. **Pivot size cap** is 1 000 000 estimated cells
   (`pivot_service.py:326`); the response is then truncated at
   `MAX_PIVOT_RESULT_ROWS = 10 000`. Anything beyond that is the user's
   responsibility to narrow via filters.
4. **Date grouping auto-adds** the field to `rows` if it is not already
   present (`pivot.js:391–394`). The behaviour is documented in the
   date-grouping card hint in `pivot.html:115–117`.
5. **Phase 5 persistence** (Save Config) is stubbed — same payload, no
   DB table yet.

These are tracked for Phase 4 / 5, not regressions.
