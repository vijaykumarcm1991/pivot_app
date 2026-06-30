# Pivot App

**Excel Pivot Analysis + Stakeholder Mailing Platform**

An internal operational web app for uploading Excel/CSV datasets, extracting
reusable metadata, configuring pivots in the browser, and computing pivots on
the backend. Future phases will add export, scheduled reports and stakeholder
mailing.

## Recent Updates

| Commit    | Description                                                                                       |
| --------- | ------------------------------------------------------------------------------------------------- |
| `f782c81` | Fix pivot grid: use `colDefs` (defined) instead of undefined `columnDefs` — AG Grid now renders.  |
| `7bfba51` | Fix bug: uploaded dataset not showing in pivot page dropdown (defensive init + lazy filter modal). |
| `e645b28` | Dark mode: fix black/grey text on white background contrast issues.                               |
| `705ef4e` | Phase 1-3 implementation + dark / light / system theme shipped.                                  |

## Tech Stack

| Layer    | Technology                                 |
|----------|--------------------------------------------|
| Backend  | FastAPI + Python 3.11                      |
| Frontend | Jinja2 + Bootstrap 5 + Vanilla JS          |
| Grid     | AG Grid Community via CDN                  |
| Database | SQLite via SQLAlchemy                      |
| Excel    | pandas + openpyxl                          |
| Deploy   | Docker Compose + Nginx                     |

## Features

- Upload `.xlsx` and `.csv` files up to 50 MB.
- Store uploaded files with UUID-based filenames (no overwrites).
- Friendly error messages for invalid file types, empty files, and corrupt files.
- Multi-sheet Excel support with per-sheet metadata.
- Inferred column datatypes: `string` (Text), `integer`, `float` (Decimal),
  `boolean`, and `datetime` (Date), with nullable detection.
- First-N-row preview (default 20 rows) of every sheet.
- Dataset management UI at `/manage` showing:
  - dataset count, total rows, total sheets
  - date / numeric / text column counts
  - per-column type and nullable flag
  - AG Grid preview
- Pivot Builder at `/pivot` with:
  - dataset → sheet → column selection
  - Rows, Columns, Values, Filters, Date Grouping
  - type-aware aggregation (text/boolean → count only; numeric/date → all)
  - per-row field sorting (asc / desc)
  - grand / row / column / subtotals toggles
  - compact vs tabular layout
  - **validation endpoint** (`POST /api/pivot/validate`) — checks the
    configuration against stored metadata without ever loading the file
  - compute endpoint (`POST /api/pivot`) — runs pandas on the backend
  - drilldown (`POST /api/pivot/drilldown`)
- **Light / Dark / System theme** with a navbar toggle.
  - Defaults to **System** (follows the OS `prefers-color-scheme`).
  - Preference is persisted in `localStorage` under `pivot-theme`.
  - Pre-paint inline script avoids flash-of-wrong-theme on first load.
  - All Bootstrap components, AG Grid, JSON debug blocks, stat cards,
    modals and form controls adapt automatically.
  - `pivot.js` defensively handles a missing/loading Bootstrap by lazily
    creating the filter modal and wrapping the init code in a
    `try { main() } catch` so a single bootstrap.CDN hiccup can't
    prevent `loadDatasets()` from running.

## Project Structure

```text
pivot-app/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config/
│   │   │   ├── database.py
│   │   │   └── settings.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── dataset.py
│   │   │   ├── sheet.py
│   │   │   └── column.py
│   │   ├── repositories/
│   │   │   ├── __init__.py
│   │   │   ├── dataset_repository.py
│   │   │   ├── sheet_repository.py
│   │   │   └── column_repository.py
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── upload_routes.py
│   │   │   ├── dataset_routes.py
│   │   │   └── pivot_routes.py
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── dataset.py
│   │   │   └── pivot.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── excel_service.py
│   │   │   ├── dataset_service.py
│   │   │   ├── pivot_service.py
│   │   │   └── pivot_validation_service.py
│   │   ├── static/
│   │   │   ├── css/styles.css
│   │   │   └── js/
│   │   │       ├── theme.js       ← light / dark / system theme switcher
│   │   │       ├── upload.js
│   │   │       ├── manage.js
│   │   │       └── pivot.js
│   │   ├── templates/
│   │   │   ├── base.html
│   │   │   ├── upload.html
│   │   │   ├── datasets.html
│   │   │   ├── preview.html
│   │   │   ├── manage.html
│   │   │   └── pivot.html
│   │   └── utils/
│   │       ├── __init__.py
│   │       └── file_utils.py
│   ├── uploads/
│   ├── generated_reports/
│   ├── requirements.txt
│   └── Dockerfile
├── nginx/
│   └── nginx.conf
├── build_start.sh
├── docker-compose.yml
├── Phase1
├── Phase2
├── Phase3
└── README.md
```

## Startup

### Docker Compose (recommended)

```bash
./build_start.sh        # builds + starts in detached mode
# OR
docker compose up --build
```

The app is served by Nginx at <http://localhost:5000>.

### Local Development

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Local app URL: <http://localhost:8000>

## Pages

| Page | Purpose |
| --- | --- |
| `/`         | Upload Excel/CSV dataset |
| `/datasets` | List uploaded datasets |
| `/preview/{id}` | Show dataset summary and first-sheet preview |
| `/manage`   | Dataset Management UI (Phase 2) |
| `/pivot`    | Pivot Builder UI (Phase 3) |
| `/docs`     | Swagger API docs |
| `/redoc`    | ReDoc API docs |

## APIs

### Phase 1 — Upload & preview

#### `POST /api/upload`

Uploads a `.xlsx` or `.csv`, stores the file with a UUID name, extracts
metadata, persists dataset/sheet/column records, and returns upload metadata
plus preview rows.

```bash
curl -X POST http://localhost:5000/api/upload \
  -F "file=@/path/to/report.xlsx"
```

Validation:

- Reject unsupported file types with `400` and a clear message.
- Reject empty files (no rows / no sheets) with `422` and a clear message.
- Enforce 50 MB upload limit with `413`.

### Phase 2 — Dataset management

#### `GET /api/datasets`

Returns all datasets ordered by most recent first.

#### `GET /api/dataset/{id}`

Returns dataset detail with sheets and inferred column metadata.

#### `GET /api/dataset/{id}/sheet/{sheet_name}/columns`

Returns stored column metadata (column name, data type, nullable) for one
sheet.

#### `GET /api/dataset/{id}/sheet/{sheet_name}/preview`

Loads the uploaded file from disk and returns the first N rows + column
metadata for one sheet.

#### `DELETE /api/dataset/{id}`

Deletes a dataset, its sheet/column metadata, and its stored file.

### Phase 3 — Pivot configuration

#### `POST /api/pivot/validate`

**Validation only — does not load or compute.** Uses the persisted metadata
to verify the configuration. Returns `{valid, errors, warnings, summary,
per_value_field}`. The UI can use this to give the user immediate feedback
before clicking "Compute".

```json
{
  "datasetId": 1,
  "sheetName": "Sales",
  "rows": ["Region"],
  "values": [{"field": "Amount", "aggregation": "sum"}],
  "filters": {"Status": ["Open", "Closed"]},
  "dateGrouping": {"OrderDate": "month"},
  "sorting": {"Region": "desc"},
  "totals": {
    "showGrandTotals": true,
    "showRowTotals": true,
    "showColumnTotals": false,
    "showSubtotals": false
  },
  "layout": "tabular"
}
```

```bash
curl -X POST http://localhost:5000/api/pivot/validate \
  -H "Content-Type: application/json" \
  -d '{"datasetId": 1, "sheetName": "Sales", "rows": ["Region"]}'
```

#### `POST /api/pivot`

Computes a pivot on the backend. Supported aggregations:
`count | sum | average | min | max`. Supported date grouping:
`year | quarter | month | week | day`. Supported layouts: `compact | tabular`.

```bash
curl -X POST http://localhost:5000/api/pivot \
  -H "Content-Type: application/json" \
  -d '{
    "datasetId": 1, "sheetName": "Sales",
    "rows": ["Region"], "columns": ["Category"],
    "values": [{"field": "Amount", "aggregation": "sum", "label": "Total"}],
    "filters": {"Status": ["Open"]},
    "dateGrouping": {"OrderDate": "month"},
    "sorting": {"Region": "desc"},
    "totals": {"showGrandTotals": true, "showRowTotals": true},
    "layout": "tabular"
  }'
```

#### `POST /api/pivot/drilldown`

Returns raw source rows matching a pivot selection.

```bash
curl -X POST http://localhost:5000/api/pivot/drilldown \
  -H "Content-Type: application/json" \
  -d '{
    "datasetId": 1, "sheetName": "Sales",
    "rows": ["Region"], "columns": ["Category"],
    "values": [{"field": "Amount", "aggregation": "sum"}],
    "selection": {"Region": "East", "Category": "Hardware"},
    "limit": 500
  }'
```

## Database Schema

### `datasets`

| Column            | Type     | Description                       |
| ---               | ---      | ---                               |
| `id`              | INTEGER  | Primary key                       |
| `filename`        | TEXT     | Original uploaded filename        |
| `stored_filename` | TEXT     | UUID-based filename on disk       |
| `upload_time`     | DATETIME | Upload timestamp                  |
| `total_rows`      | INTEGER  | Row count from the first sheet    |
| `total_columns`   | INTEGER  | Column count from the first sheet |

### `dataset_sheets`

| Column       | Type    | Description                                       |
| ---          | ---     | ---                                               |
| `id`         | INTEGER | Primary key                                       |
| `dataset_id` | INTEGER | FK → `datasets.id` (cascade delete)               |
| `sheet_name` | TEXT    | Excel sheet name, or `Sheet1` for CSV             |
| `row_count`  | INTEGER | Number of rows in the sheet                       |

### `dataset_columns`

| Column         | Type     | Description                                       |
| ---            | ---      | ---                                               |
| `id`           | INTEGER  | Primary key                                       |
| `dataset_id`   | INTEGER  | FK → `datasets.id`                                |
| `sheet_id`     | INTEGER  | FK → `dataset_sheets.id`                          |
| `sheet_name`   | TEXT     | Sheet name                                        |
| `column_name`  | TEXT     | Column name from the source file                  |
| `data_type`    | TEXT     | Inferred datatype                                 |
| `is_nullable`  | BOOLEAN  | Whether null values were detected                 |

## Inferred Datatypes

The frontend and backend agree on these type values:

| Internal | UI label | Notes                                            |
| ---      | ---      | ---                                              |
| `string`   | Text     | Any non-numeric, non-date, non-bool column     |
| `integer`  | Integer  | Whole numbers                                   |
| `float`    | Decimal  | Floating-point numbers                          |
| `boolean`  | Boolean  | True/False, yes/no, or a numeric column whose non-null values are all 0.0 or 1.0 (typical Excel bool roundtrip) |
| `datetime` | Date     | Anything pandas can parse as a timestamp        |

## Manual Test Checklist

### Theme

1. Open the app — it should match your OS theme (light/dark) on first load.
2. Click the theme toggle in the navbar (top right).
3. Switch to **Dark** — entire UI (cards, tables, AG Grid, modal) flips.
4. Switch to **Light** — entire UI flips back.
5. Switch to **System** — page follows your OS setting; toggle your OS
   theme and the page follows live.
6. Reload the page — your last selected mode is remembered.

## Theme (Light / Dark / System)

The app supports a three-mode theme:

- **System** (default) — follows the OS `prefers-color-scheme: dark` and
  re-applies automatically when the user toggles their OS theme.
- **Light** — forced light theme.
- **Dark** — forced dark theme.

The current mode is persisted in `localStorage` under the `pivot-theme`
key. The theme is set on the `<html>` element via the `data-bs-theme`
attribute that Bootstrap 5.3+ uses to drive its dark/light token set.

To prevent flash-of-wrong-theme on first paint, a small inline script in
`base.html` runs *before* any CSS is applied, reads the stored mode,
resolves it (taking the system preference into account for "system"),
and sets the `data-bs-theme` attribute synchronously. The full
`theme.js` then takes over to wire the toggle UI, listen for OS theme
changes, and re-skin the AG Grid wrapper by toggling
`ag-theme-alpine` ↔ `ag-theme-alpine-dark`.

Custom dark-mode overrides live in `backend/app/static/css/styles.css`.
The CSS uses Bootstrap 5.3's CSS custom properties (`--bs-body-bg`,
`--bs-body-color`, `--bs-tertiary-bg`, `--bs-border-color-translucent`,
`--bs-card-bg`, `--bs-secondary-color`, etc.) directly, so every styled
element automatically follows the active theme without needing a
separate `[data-bs-theme="dark"]` rule for each one.

The following elements adapt to dark mode:

- body background and text colour
- `.card` (with a subtle border in dark mode for cards that use
  `.border-0` so they don't blend into the background)
- `.card-header`
- `.table` thead, tbody, and row hover
- `.table-light` (overridden to use `--bs-tertiary-bg` so it adapts)
- `.form-control`, `.form-select`, `.input-group-text` (with proper
  focus state)
- `.modal-content`, `.modal-header`, `.modal-footer`, `.modal-backdrop`
- `.dropdown-menu`, `.dropdown-item`
- `.list-group-item`
- `pre` (JSON debug blocks)
- `.alert-secondary` (file info)
- `.btn-link`, `.btn-close`
- the `.drop-zone` (upload page)
- `.text-muted` (so it stays readable in dark mode)
- the navbar (kept dark in both modes for a solid brand anchor, but
  the dark-mode shade is even deeper)

The dark mode **contrast ratio** for body text on body background is
about **11.85 : 1**, comfortably above the WCAG AA threshold of 4.5 : 1.
The same ratio holds for table headers, card bodies, and badge text.

### Phase 1
3. Upload a normal `.xlsx` → confirm redirect to `/preview/{id}`.
4. Upload a `.csv` → confirm preview generates correctly.
5. Upload a `.pdf` → confirm `400` with a clear message.
6. Upload an empty `.xlsx` → confirm `422` with a clear message.
7. Upload a multi-sheet `.xlsx` → confirm all sheets are listed.
8. Restart the app → confirm previously uploaded files still exist.
9. Check the database (3 tables: `datasets`, `dataset_sheets`, `dataset_columns`).
10. Verify the preview table shows only the first 20 rows.
11. Run `docker compose config` to validate the compose file.

### Phase 2

1. Open `/manage`, select a dataset → confirm sheet dropdown populates.
2. Select a sheet → confirm AG Grid preview loads.
3. Verify Text / Decimal / Date / Boolean columns are identified correctly.
4. Verify nullable detection on columns containing empty values.
5. Verify the first 100 rows are displayed for the selected sheet.
6. Restart the app → confirm previously uploaded datasets are still available.
7. Confirm dataset information, sheets, and metadata are displayed correctly.
8. Hit each `GET /api/dataset/...` endpoint manually — they should all return
   JSON.
9. Upload a workbook with around 10 000 rows — upload + metadata should
   complete without errors.
10. Upload a workbook with mixed/invalid values — metadata should still be
    generated where possible.

### Phase 3

1. Open `/pivot`, select a dataset → sheets load.
2. Select a sheet → columns load (re-fetches when sheet changes).
3. Add fields to Rows / Columns / Values / Filters.
4. Add a Value with a text field — only "Count" should be selectable.
5. Add a Value with a numeric field — all aggregations appear.
6. Add a Date field — date-grouping card appears.
7. Add a filter → multi-value picker modal opens (no `prompt()`).
8. Configure Layout (compact vs tabular) — selection is stored.
9. Configure Totals (Grand / Row / Column / Subtotals) — selections stored.
10. Configure sorting (per Row field) — selection is stored.
11. Click **Validate** → `/api/pivot/validate` returns structured
    `valid / errors / warnings / summary / per_value_field`.
12. Click **Compute** → `/api/pivot` returns the full pivot and the AG Grid
    renders it.
13. Submit an invalid configuration — backend returns meaningful errors.
14. Inspect the generated JSON — it contains everything required to recreate
    the pivot later (dataset, sheet, rows, columns, values, aggregations,
    filters, dateGrouping, sorting, totals, layout).
15. Review the code — UI logic, validation logic and API logic are cleanly
    separated (see `pivot_validation_service.py` vs `pivot_service.py`).

## Pivot Architecture

- `pivot_routes.py` exposes the Phase 3 APIs.
- `pivot.py` (schemas) defines the request and response contracts, including
  the new `TotalsOptions` and `sorting` fields.
- `pivot_validation_service.py` validates a request against stored metadata
  **without loading the file** (Phase 3 spec).
- `pivot_service.py` is the only pivot calculation layer; it loads source
  data from the uploaded file, applies filters, creates date-group helper
  columns, calculates the pivot with pandas, flattens MultiIndex output for
  JSON, applies per-row sorting, and honours the totals toggles.
- The frontend (`pivot.js`) is responsible only for collecting the
  configuration and rendering the response.
- Drilldown reuses the same filter and date-grouping path, then applies the
  selected row/column values to return matching raw records.

## Performance Considerations

- The engine is designed for uploaded datasets up to about 50 000 rows.
- Metadata is persisted in SQLite, but pivot calculations intentionally
  re-read the uploaded sheet so the backend remains the source of truth.
- Date-grouping helper columns are generated in-memory per request.
- Pivot result cells are pre-estimated; results larger than ~1 M cells are
  rejected up front.
- Drilldown responses are capped by `limit` and hard-limited to 5 000 rows to
  avoid oversized API responses.
- Future export, scheduled report, mailing, and saved-pivot features can
  reuse the same `PivotRequest` contract.

## Implementation Notes

- Upload validation lives in `upload_routes.py` and `file_utils.py`.
- pandas parsing, datatype inference (with 0/1 float heuristic), and
  empty-file detection live in `excel_service.py`.
- Sheet and column metadata persistence lives in `dataset_service.py`.
- Backend pivot calculation and drilldown live in `pivot_service.py`.
- Pivot validation lives in `pivot_validation_service.py` (no file I/O).
- SQLAlchemy table creation runs from `init_db()` during FastAPI startup;
  the `models/__init__.py` import side-effect ensures every model is
  registered.
- Templates and static files are served via FastAPI's built-in mounts
  (proxied by Nginx in production).
- Uploaded files, generated reports, and SQLite data are persisted through
  Docker volumes.
