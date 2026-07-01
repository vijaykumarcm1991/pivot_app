# Pivot App

**Excel Pivot Analysis + Stakeholder Mailing Platform**

An internal operational web app for uploading Excel/CSV datasets, extracting
reusable metadata, configuring pivots in the browser, and computing pivots on
the backend. Future phases will add export, scheduled reports and stakeholder
mailing.

## Recent Updates

| Commit    | Description                                                                                       |
| --------- | ------------------------------------------------------------------------------------------------- |
| (latest)  | **Phase 6 — Email composition**: Send Email button on the Pivot page → composer modal (To/CC/BCC + Subject + Message) with HTML preview, .xlsx attachment, SMTP settings page, email history page, recent-recipient autocomplete, and 11 new API endpoints. The grand-total block in the email body is disabled (it was rendering blank in V1) — the pivot summary table is still rendered. |
| (latest)  | **Phase 5 — Drill-down**: double-click or multi-select pivot rows → Bootstrap modal with raw records, dedup, search, column visibility, matching-criteria card, summary card, and reusable Excel export. |
| (latest)  | Add view controls on `/pivot`: hidable configuration panel + fullscreen pivot result overlay.     |
| (latest)  | Fix tabular view: row fields are now shown as their own columns (no auto "Group" column collapse). |
| `fa4b8ca` | Phase 4 implemented — Excel-like AG Grid result UI, Pivot Statistics, client-side Excel export.   |
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
- **Excel-like AG Grid result** (Phase 4) with:
  - column resize / reorder / sort / filter / text search (quickFilter)
  - sticky header, pagination (20 / 50 / 100 / 200), horizontal scroll
  - checkbox row selection (single + multi, Select All, Clear) and three
    counters — Selected / Visible / Groups
  - pinned-bottom **Grand Total** row (green tint) and **Row Total**
    column (blue tint)
  - **Compact + Tabular** layouts: tabular shows every row field as its
    own column (one column per row field), compact combines them into a
    single `Rows` column with `"a / b / c"` paths.
  - **Pivot Statistics panel** with 8 stat cards (Dataset, Sheet, Source
    Rows, Rows After Filters, Pivot Rows, Layout, Date Grouping,
    Aggregations).
- **Client-side Excel export** of the current view via SheetJS — headers,
  visible rows in current sort + filter order, grand total row appended.
- **Drill-down on pivot rows** (Phase 5) — open the raw records behind any
  pivot result in a Bootstrap modal:
  - **Two triggers** — double-click a pivot row, *or* select one or more
    rows and click the new **Drill-down** button in the action toolbar.
  - **Multi-row drilldown with deduplication** — selecting several rows
    produces a single merged view; identical raw records are detected
    via a stable JSON key (`Object.keys(record).sort().map(...)`) and
    never appear twice. `metadata.matched_rows` is the additive total;
    `metadata.returned_rows` is the post-dedup count.
  - **Selection summary card** — Dataset, Sheet, Selected Pivot Rows,
    Matching Records, Returned Records, populated from the drilldown
    response metadata.
  - **Matching criteria card** — pills like `Region = North`,
    `Category = Payments` so the user can see exactly which pivot
    values produced the records on screen.
  - **Dedicated AG Grid** (independent from the pivot grid) with
    sorting, filtering, column resizing, pagination, and built-in
    copy (Ctrl+C copies the selected cells, or the whole row when
    no cells are selected).
  - **Search box** (quick filter) filters the grid immediately.
  - **Column visibility menu** — show / hide / "all" / "none" / reset.
  - **Polished UI** — sticky header, sticky toolbar, record counter,
    loading overlay with progress (`"3 / 5 groups · Region=North"`),
    and a friendly empty state when no records match.
  - **Excel export** of the visible drill-down view — headers,
    current sort, current filter, visible columns only. The same
    helper (`DrilldownExport.buildWorkbookFromView`) is the reusable
    form for the upcoming **email phase** (Phase 6) — it accepts any
    `(columns, rows)` pair and returns a SheetJS workbook ready to
    be attached to an email, no backend round-trip required.
- **Stakeholder email composition** (Phase 6) — send the selected
  pivot row(s) + drill-down attachment by email from the Pivot page:
  - **Send Email button** on the Pivot page action toolbar. Enabled
    only when at least one pivot row is selected (wired through
    `PivotGrid`'s `onSelectionChange` context callback).
  - **Email Composer modal** with:
    - **To / CC / BCC** fields — accept a JSON list OR a string with
      addresses separated by commas, semicolons, or newlines.
    - **Recent-recipient autocomplete** — typeahead suggestions
      pulled from `/api/email/recent-recipients?type=to|cc|bcc`. The
      same address can be remembered separately for To/CC/BCC.
    - **Subject + user message** (plain text, newlines preserved as
      `<br>` in the email body).
  - **Preview button** — `POST /api/email/preview` builds the HTML
    body and the .xlsx attachment. The preview shows the rendered
    email in an iframe + a download link for the attachment.
  - **Send button** — `POST /api/email/send` validates addresses +
    SMTP settings + attachment, dispatches via SMTP, records the
    outcome in `email_history`, and remembers the recipients for
    autocomplete next time.
  - **Email body** (built server-side with table-based layout +
    inline CSS for Outlook/Gmail compatibility):
    - Subject bar (blue)
    - User's message
    - **Pivot summary table** with the selected pivot rows
      (column headers + data rows)
    - "The detailed drill-down report is attached." line
    - Footer: Generated By, Generated On, Dataset, Sheet
    - **Grand-total block is NOT rendered** — it was blank in V1
      because the engine returns `totals.grand` keyed by value-label
      and the column-name alignment was fragile. The grand totals are
      still in the .xlsx attachment.
  - **Attachment** is a single .xlsx file with the merged raw
    records across all selected pivot rows, with dedup (same stable
    JSON key as the drilldown modal). Filename pattern:
    `Pivot_Drilldown_YYYY-MM-DD_HH-MM.xlsx`.
- **SMTP Settings page** (`/email/settings`) — configure SMTP host,
  port, username, password (masked in the GET response, sent as
  plain text), TLS, sender name, sender email. Password is stored
  in SQLite (plaintext for V1; encryption is a future hardening
  pass). A "Send test email" button verifies the credentials.
- **Email History page** (`/email/history`) — list of every email
  with date/time, subject, recipients, dataset/sheet, pivot-row
  count, attached-records count, status (Sent / Failed), and a
  clickable error message for failures. Each successful entry has
  a **re-download** button for the .xlsx attachment.
- **View controls on the Pivot page** (post-Phase 4):
  - **Hide / Show configuration panel** — collapses the left
    configuration column; the result column expands to full width.
  - **Fullscreen pivot result** — overlay that makes the result panel
    cover the viewport with the grid growing to `calc(100vh - 240px)`.
    **ESC** also exits fullscreen. The debug / JSON card is auto-hidden
    in fullscreen to keep focus on the result.
  - Both buttons live in the sticky actions card so they're always
    reachable. State is in-memory only (resets on reload).
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
│   │   │   ├── pivot.py
│   │   │   └── email.py                  ← Phase 6
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── excel_service.py
│   │   │   ├── dataset_service.py
│   │   │   ├── pivot_service.py
│   │   │   ├── pivot_validation_service.py
│   │   │   ├── attachment_service.py     ← Phase 6 — builds the .xlsx
│   │   │   ├── smtp_service.py           ← Phase 6 — smtplib wrapper
│   │   │   ├── email_service.py          ← Phase 6 — orchestrator + HTML
│   │   │   └── email_history_service.py  ← Phase 6 — read-side
│   │   ├── static/
│   │   │   ├── css/styles.css
│   │   │   └── js/
│   │   │       ├── theme.js              ← light / dark / system theme switcher
│   │   │       ├── upload.js
│   │   │       ├── manage.js
│   │   │       ├── pivot.js              ← controller (~1100 lines)
│   │   │       ├── pivot-grid.js         ← AG Grid wrapper (Phase 4)
│   │   │       ├── pivot-export.js       ← SheetJS exporter (Phase 4)
│   │   │       ├── drilldown-selection.js ← selection-criteria builder (Phase 5)
│   │   │       ├── drilldown-manager.js   ← modal orchestrator (Phase 5)
│   │   │       ├── drilldown-export.js    ← drill-down .xlsx exporter (Phase 5)
│   │   │       ├── email-manager.js       ← Phase 6 — composer modal
│   │   │       ├── preview-manager.js     ← Phase 6 — HTML preview
│   │   │       ├── smtp-settings.js       ← Phase 6 — settings page
│   │   │       └── email-history.js       ← Phase 6 — history page
│   │   ├── templates/
│   │   │   ├── base.html
│   │   │   ├── upload.html
│   │   │   ├── datasets.html
│   │   │   ├── preview.html
│   │   │   ├── manage.html
│   │   │   ├── pivot.html
│   │   │   ├── email_settings.html       ← Phase 6
│   │   │   └── email_history.html        ← Phase 6
│   │   └── utils/
│   │       ├── __init__.py
│   │       └── file_utils.py
│   ├── uploads/
│   ├── generated_reports/
│   │   ├── email_previews/              ← Phase 6 (one-shot preview attachments)
│   │   └── email_attachments/           ← Phase 6 (attachments for re-download)
│   ├── requirements.txt
│   └── Dockerfile
├── nginx/
│   └── nginx.conf
├── build_start.sh
├── docker-compose.yml
├── PIVOT_CONTRACT.md
├── Phase1
├── Phase2
├── Phase3
├── Phase4
└── README.md
```

### Frontend module split (`backend/app/static/js/`)

| File | Role |
| --- | --- |
| `pivot.js`              | Controller — owns `appState`, left config panel, `buildPayload()`, validate / compute flow, stats panel, selection bar, search input, export + drill-down + email orchestration, view toggles (hide config / fullscreen), defensive `try { main() } catch` init, lazy filter modal, theme listener. Exposes `window.PivotAppState()` for the drilldown / email managers. Dispatches `pivot:computed` after every successful compute. |
| `pivot-grid.js`         | Pure AG Grid wrapper for the **pivot result**. Exposes `window.PivotGrid` with `render / clear / getSelectedRows / getSelectedCount / getSelectedGroups / getTotalRowCount / selectAll / clearSelection / setSearchTerm / getVisibleColumns / getVisibleRows / getLastResponse / getLastContext`. The `render()` context now supports an `onRowDoubleClick(row)` callback (Phase 5, drilldown) AND an `onSelectionChange(count, rows)` callback (Phase 6, enable/disable the Send Email button). |
| `pivot-export.js`       | SheetJS export of the **pivot result**. Exposes `window.PivotExport.exportCurrentView()` and `setNotifier()`. Mirrors what the user sees in the grid. |
| `drilldown-selection.js` | **Phase 5** — builds the `selection` map that goes into `POST /api/pivot/drilldown`. Exposes `window.DrilldownSelection` with `buildSelectionForRow`, `buildSelectionList`, `getSelectedPivotRows`, `getCurrentPivotResponse`, and `dedupKey` (stable JSON dedup key used by the merge loop AND by the email attachment service). |
| `drilldown-manager.js`   | **Phase 5** — modal orchestrator. Exposes `window.DrilldownManager` with `open / openForCurrentSelection / openForRow / close / hasData / getCurrentDataset / getCurrentContext / getVisibleColumns / getVisibleRows`. Owns the AG Grid instance, the toolbar (search + column visibility + reset + export), the summary card, the matching-criteria card, the loading overlay, the empty state, and the dedup + merge loop. Listens for `pivot:computed` to clear the cache and for `theme:changed` to re-skin the grid. |
| `drilldown-export.js`    | **Phase 5** — SheetJS export of the **drill-down** view. Exposes `window.DrilldownExport.exportCurrentView()` and the pure helper `buildWorkbookFromView(columns, rows, options)` that returns a SheetJS workbook — the reusable form for the email phase (Phase 6) so attachments can be generated without a backend round-trip. |
| `email-manager.js`       | **Phase 6** — Email Composer modal orchestrator. Exposes `window.EmailManager` with `open / close / getState`. Wires the form (To/CC/BCC/Subject/Message), the recipient typeahead, the Preview / Send / Reset buttons, the iframe-rendered HTML preview, and the attachment download card. Reuses `DrilldownSelection` to build the per-row selections. |
| `preview-manager.js`     | **Phase 6** — Renders the server-built HTML email inside the composer's preview pane (sandboxed iframe). Exposes `window.PreviewManager.setHtml / setAttachment / setBusy / clear`. |
| `smtp-settings.js`       | **Phase 6** — SMTP settings page controller. Exposes the form at `/email/settings` — load / save / send-test. The password field is always blank in the form (the server never returns the password; it returns `passwordSet: true/false`). |
| `email-history.js`       | **Phase 6** — Email history page controller. Exposes `/email/history` — list with search + status filter, clickable error messages, re-download buttons. |
| `manage.js`             | `/manage` page: dataset + sheet selection, column type table, AG Grid preview, delete flow, theme listener. |
| `upload.js`             | Drag-and-drop + form submit for the upload page. |
| `theme.js`              | `window.ThemeManager` — `setMode / getStoredMode / getCurrentTheme / syncToggleUI / applyTheme`; dispatches `theme:changed` CustomEvent. |

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

### Phase 6 — Email composition

All Phase 6 endpoints are prefixed with `/api/email/` (or `/email/`
for the page routes). The request body shape for `/preview` and
`/send` is the same — the diff is that `/preview` returns the
generated HTML + a one-shot attachment download URL, while `/send`
actually dispatches via SMTP and records the outcome.

#### `GET /api/email/smtp-settings` / `POST /api/email/smtp-settings`

Load or save the singleton SMTP configuration. The GET response
returns `passwordSet: bool` instead of the password itself. On
save, an empty `password` field means "keep the existing password".

```json
{
  "host": "smtp.gmail.com",
  "port": 587,
  "username": "user@example.com",
  "password": "",
  "useTls": true,
  "senderName": "Pivot App",
  "senderEmail": "reports@example.com"
}
```

```bash
curl -X POST http://localhost:5000/api/email/smtp-settings \
  -H "Content-Type: application/json" \
  -d '{"host":"smtp.gmail.com","port":587,"username":"u","password":"p","useTls":true,"senderName":"P","senderEmail":"p@x.com"}'
```

#### `POST /api/email/test`

Send a one-off test email to a single address. Returns 502 if the
SMTP server rejects the credentials / unreachable.

#### `POST /api/email/preview`

Build the HTML email body + the .xlsx attachment without sending.
The client uses the returned `attachmentDownloadUrl` to offer a
download link so the user can verify the file before clicking
Send. Request body:

```json
{
  "to": ["alice@example.com", "bob@example.com"],
  "cc": ["carol@example.com"],
  "bcc": [],
  "subject": "Weekly report",
  "message": "Hello team,\n\nPlease find the report below.\n\nRegards,",
  "datasetId": 1,
  "sheetName": "Sales",
  "rows": ["Region", "Category"],
  "columns": [],
  "values": [{"field":"Amount","aggregation":"sum","label":"sum_Amount"}],
  "filters": {},
  "dateGrouping": {},
  "sorting": {},
  "totals": {"showGrandTotals": true, "showRowTotals": true},
  "layout": "tabular",
  "selections": [
    {"selection": {"Region": "North", "Category": "Payments"}},
    {"selection": {"Region": "South", "Category": "Refunds"}}
  ],
  "pivot_rows": [
    {"Region": "North", "Category": "Payments", "sum_Amount": 449.5},
    {"Region": "South", "Category": "Refunds",  "sum_Amount": 125.0}
  ],
  "pivot_response": {
    "columns": ["Region", "Category", "sum_Amount"],
    "totals": {"grand": {"sum_Amount": 574.5}, "row_total_field": "row_total"}
  },
  "dataset_name": "sales-2024.xlsx"
}
```

Response includes the rendered `html`, the `attachmentFilename`,
a one-shot `attachmentDownloadUrl`, and the `attachmentRecordCount`
(records after dedup).

#### `POST /api/email/send`

Same request body as `/preview`. Validates addresses + SMTP
settings, builds the attachment, dispatches via SMTP, records the
outcome in `email_history`, and remembers the recipients for
autocomplete. Returns the new `historyId` on success.

#### `GET /api/email/history?limit=100`

List past emails (most recent first). Each entry includes
`sentAt`, `subject`, `to/cc/bccAddresses`, `datasetName`,
`sheetName`, `pivotRowsCount`, `attachedRecordsCount`, `status`
(`success` / `failed`), `errorMessage`, `attachmentFilename`, and
`hasAttachment` (whether the on-disk file is still present).

#### `GET /api/email/recent-recipients?type=to|cc|bcc`

Return the most recently used addresses for autocomplete. The
optional `type` filter limits the list to one recipient type.

#### `GET /api/email/preview-attachment/{rel-path}` / `GET /api/email/history/{id}/attachment`

Download a generated attachment. Preview attachments are
one-shot (path is relative to `REPORTS_DIR/email_previews/`);
history attachments persist for re-download.

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

### `smtp_settings` (Phase 6)

Singleton row (`id = 1` always). Stores the SMTP credentials the
email service uses when sending.

| Column         | Type     | Description                                       |
| ---            | ---      | ---                                               |
| `id`           | INTEGER  | Always `1` (singleton)                            |
| `host`         | TEXT     | SMTP server hostname                              |
| `port`         | INTEGER  | SMTP server port (typically 587 for STARTTLS)     |
| `username`     | TEXT     | SMTP username                                     |
| `password`     | TEXT     | SMTP password — **plaintext in V1**; encryption is a future hardening pass |
| `use_tls`      | BOOLEAN  | Use STARTTLS (recommended)                        |
| `sender_name`  | TEXT     | Display name for outgoing emails                  |
| `sender_email` | TEXT     | "From" address                                     |
| `updated_at`   | DATETIME | Last update timestamp                             |

### `email_history` (Phase 6)

One row per email the user sends. Passwords are never stored here.

| Column                    | Type     | Description                                       |
| ---                       | ---      | ---                                               |
| `id`                      | INTEGER  | Primary key                                       |
| `sent_at`                 | DATETIME | Send timestamp                                    |
| `subject`                 | TEXT     | Email subject                                     |
| `to_addresses_json`      | TEXT     | JSON array of To addresses                        |
| `cc_addresses_json`      | TEXT     | JSON array of CC addresses                        |
| `bcc_addresses_json`     | TEXT     | JSON array of BCC addresses                       |
| `dataset_id`              | INTEGER  | FK → `datasets.id` (informational)               |
| `dataset_name`            | TEXT     | Original upload filename                         |
| `sheet_name`              | TEXT     | Sheet the pivot was built from                    |
| `pivot_rows_count`        | INTEGER  | Number of pivot rows the user sent                |
| `attached_records_count`  | INTEGER  | Number of records in the .xlsx (post-dedup)       |
| `status`                  | TEXT     | `success` or `failed`                             |
| `error_message`           | TEXT     | Failure reason (NULL on success)                  |
| `attachment_filename`     | TEXT     | The .xlsx filename (e.g. `Pivot_Drilldown_…xlsx`)  |
| `attachment_path`         | TEXT     | Relative path under `REPORTS_DIR/email_attachments/` |
| `pivot_payload_json`      | TEXT     | JSON snapshot of the request — lets the history page re-render the email body without re-querying the dataset |

### `recent_recipients` (Phase 6)

Drives the To/CC/BCC autocomplete. The same address is remembered
once per recipient type, so `alice@x.com` can be suggested for To
and CC independently.

| Column          | Type     | Description                                       |
| ---             | ---      | ---                                               |
| `id`            | INTEGER  | Primary key                                       |
| `address`       | TEXT     | Email address (lowercased + trimmed)              |
| `recipient_type`| TEXT     | `to` / `cc` / `bcc`                                |
| `last_used_at`  | DATETIME | Last time the user sent to this address           |
| `use_count`     | INTEGER  | How many times this address was used               |

Unique constraint on `(address, recipient_type)`.

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

### Phase 4

1. Generate a pivot — AG Grid renders with all columns visible.
2. Resize / reorder / sort / filter columns.
3. Type in the search box → only matching rows stay visible.
4. Select one or more rows — the **Selection** counter updates.
5. Click **Select All** (visible) / **Clear** — counts update accordingly.
6. **Tabular** layout with 2+ row fields → each row field is its **own
   column** (no auto "Group" column collapse). The grid should look like a
   flat Excel pivot, with the value columns on the right.
7. **Compact** layout with 2+ row fields → row fields are merged into a
   single `Rows` column with values like `"a / b / c"`.
8. Toggle Grand Totals / Row Totals on / off — pinned row / column update.
9. Click **Export** → an `.xlsx` file downloads containing the headers,
   visible rows in current sort + filter order, and the grand total row.
10. Refresh / regenerate the pivot — stale data is cleared before the new
    result paints.

### View controls (post-Phase 4)

1. Click **Hide Config** in the actions card → the left configuration
   column collapses; the result column expands to full width. The button
   icon flips to `chevron-double-right` and the label becomes
   **Show Config**.
2. Click **Show Config** → the configuration column reappears and the
   result column goes back to `col-lg-8`.
3. Click **Fullscreen** → the result panel becomes a fixed overlay
   covering the viewport; the grid grows to `calc(100vh - 240px)`; the
   debug card is auto-hidden. The button icon becomes
   `fullscreen-exit` and the label becomes **Exit Fullscreen**.
4. Press **ESC** (or click the fullscreen button again) → the overlay
   closes and the page returns to the normal layout.
5. Combine both: hide the config panel **and** enter fullscreen — the
   result should fill the entire viewport, the config stays hidden, and
   the two toggles remain independent.

### Phase 5 — Drill-down

1. Generate a pivot, then **double-click any data row** — the drill-down
   modal opens with the matching raw records. The grand-total pinned row
   is excluded from the trigger.
2. Select one pivot row and click the **Drill-down** button in the
   action toolbar — the modal opens for that single row.
3. Select **multiple** pivot rows and click **Drill-down** — the modal
   opens with a **single merged view**; identical records are shown
   once. The summary card displays `Matched = sum(matched_rows)`
   (additive) and `Returned` (post-dedup). For non-overlapping rows
   they should be equal; for overlapping rows `Matched > Returned`.
4. Open a drilldown, then **re-generate the pivot** — close and
   re-open the modal. The dataset cache should be cleared (the
   `pivot:computed` event handler) so the modal cannot show records
   from the previous run.
5. **Search** inside the drill-down grid — only matching rows stay
   visible. The record counter updates to `"N of M records"`.
6. **Sort** any column — rows reorder; the export will match.
7. **Resize** columns — widths persist for the current session.
8. **Hide** one or more columns via the **Columns** dropdown — the
   grid reflows; **Reset** restores all columns; **All / None**
   shortcuts work.
9. Click **Export** — an `.xlsx` file downloads with the headers,
   current sort + filter, and only the visible columns. Open it and
   verify the row count matches the visible records in the grid.
10. Drill into a row with **no matching records** — a friendly
    empty state appears (`<icon> No matching records`) instead of an
    empty grid.
11. **Copy** selected cells in the drill-down grid (Ctrl+C) — the
    selection is copied with headers. **Copy** a whole row by
    clicking a cell in that row and pressing Ctrl+C.
12. Verify the **matching-criteria card** at the top — pills like
    `Region = North`, `Category = Payments` show the values that
    produced the records. For multi-row drilldown, each selected
    pivot row gets its own group of pills (`Row 1:`, `Row 2:`, …).
13. Close and reopen the modal — the application remains stable
    and selections are handled correctly.
14. Review the code — drill-down, export and selection logic are
    in three separate files (`drilldown-manager.js`,
    `drilldown-export.js`, `drilldown-selection.js`) and the
    spreadsheet export is a reusable pure function
    (`buildWorkbookFromView`) that the upcoming email phase can
    call without re-querying the backend.

### Phase 6 — Stakeholder email

1. **Configure SMTP** on `/email/settings` — fill in host, port,
   username, password, sender name, sender email. The password
   is masked in the GET response; leave the field blank on save
   to keep an existing password.
2. Click **Send Test Email** on the settings page — verify the
   SMTP credentials work before sending a real report. (You'll
   need a real reachable SMTP server for this; otherwise the
   request will return 502 with the SMTP error message.)
3. Generate a pivot, then click **Send Email** in the action
   toolbar — the Email Composer modal opens. With no rows
   selected, the button is disabled.
4. Select **one** pivot row and click **Send Email** — the modal
   opens for that single row. The right-hand "Pivot Rows
   Selected" badge shows `1`.
5. Select **multiple** pivot rows and click **Send Email** — the
   modal opens; the badge shows the count. The attachment
   contains the **merged, deduplicated** raw records across all
   selected rows.
6. **Enter multiple To addresses** in a single field — paste
   `alice@x.com, bob@x.com; carol@x.com`. The server splits on
   `,`, `;`, and newlines. Invalid addresses produce a 400.
7. Click **Preview** — the HTML body renders inside an iframe
   in the left pane. Verify the **pivot summary table** is
   visible (selected rows + column headers) and that the
   **"The detailed drill-down report is attached."** line is
   below it. The grand-total block is intentionally **not**
   rendered in V1.
8. Click the **attachment card** to download the generated
   `.xlsx` — open it and verify the row count matches what the
   summary card showed.
9. Type in the **To / CC / BCC** field after sending a few emails
   — recently used addresses appear as suggestions (click to
   append). The suggestions are remembered on both success and
   SMTP failure (the failure is on the server, not a typo).
10. Click **Send** — a success toast appears with the new
    `history_id` (or an error toast if SMTP fails). The recipients
    are remembered for autocomplete next time.
11. Open `/email/history` — the new email appears at the top
    with subject, recipients, dataset, sheet, pivot rows count,
    attached records count, status badge. Successful entries
    have a **re-download** button for the .xlsx.
12. Click a **Failed** status badge — the error message is
    displayed in a modal so the user can read it without leaving
    the page.
13. **Restart the application** — SMTP settings, email history,
    and recent recipients are all persisted in SQLite and
    reappear on the next session.
14. Review the code — composition, SMTP, attachment generation,
    and history are **separate modules**:
    - `email_service.py` orchestrates
    - `attachment_service.py` builds the .xlsx
    - `smtp_service.py` is the SMTP transport wrapper
    - `email_history_service.py` is the read-side
    - `email_routes.py` ties it all together
    - Frontend: `email-manager.js` (composer), `preview-manager.js`
      (preview), `smtp-settings.js` (settings), `email-history.js`
      (history)
    - The `EmailSendRequest` shape has separate `selections` and
      `pivot_rows` fields so future phases can add recipient
      rules or saved templates without breaking the contract.

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

## View Controls (Pivot page)

Two buttons in the sticky **actions card** (top of the result panel)
control how the result is presented:

| Button | Effect | Implementation |
| --- | --- | --- |
| **Hide / Show Config** | Toggles `#configPanel` (`col-lg-4`) on / off. The result column flips between `col-lg-8` and `col-lg-12`. | `pivot.js` → `setConfigHidden()` |
| **Fullscreen** | Toggles `.pivot-fullscreen` on `#resultPanel` (position: fixed, full viewport, `z-index: 1050`). Grid grows to `calc(100vh - 240px)`. Body scroll is locked. Debug card is hidden. **ESC** also exits. | `pivot.js` → `setFullscreen()` + `keydown` listener |

Both buttons update their icon, label, and ARIA state (`aria-expanded` /
`aria-pressed`) on toggle. The state is in-memory only and resets on page
reload. The CSS lives in `backend/app/static/css/styles.css` (see
`.pivot-fullscreen`, `body.pivot-fullscreen-active`).

## Performance Considerations

- The engine is designed for uploaded datasets up to about 50 000 rows.
- Metadata is persisted in SQLite, but pivot calculations intentionally
  re-read the uploaded sheet so the backend remains the source of truth.
- Date-grouping helper columns are generated in-memory per request.
- Pivot result cells are pre-estimated; results larger than ~1 M cells are
  rejected up front.
- Drilldown responses are capped by `limit` and hard-limited to 5 000 rows to
  avoid oversized API responses.
- Email attachments reuse the same drilldown pipeline (one drilldown call
  per selected pivot row, then merged with dedup). The same 5 000-row cap
  applies to the per-selection call. A multi-row email that selects three
  pivot rows covering 8 000 raw records will produce an attachment with
  at most 5 000 unique records (per-selection cap) plus a `matchedRows` /
  `attachedRecordsCount` pair in the response so the user can see how many
  were dropped.
- Email previews and sent attachments are persisted to
  `REPORTS_DIR/email_previews/` and `REPORTS_DIR/email_attachments/`
  respectively, so the user can re-download from the history page.
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
- **Phase 4 frontend split** (under `backend/app/static/js/`):
  - `pivot.js` is the controller. It owns the configuration UI, the
    validate / compute flow, the stats / selection / search orchestration,
    the empty-state machinery, the view toggles (hide config / fullscreen),
    the defensive `try { main() } catch` init, and the lazy filter-modal
    helper that prevents a missing Bootstrap from breaking the page.
  - `pivot-grid.js` is a pure AG Grid wrapper. It exposes a small API
    (`render / clear / getSelectedRows / getSelectedCount / getSelectedGroups
    / selectAll / clearSelection / setSearchTerm / getVisibleColumns /
    getVisibleRows / getLastResponse / getLastContext`) and reuses the
    same grid instance across renders via `setGridOption`.
  - `pivot-export.js` is a thin SheetJS wrapper that exports the
    currently visible view (headers, visible rows in sort + filter order,
    grand total row appended) to `.xlsx`.
  - `theme.js` exposes `window.ThemeManager` and re-skins the AG Grid
    wrapper on `theme:changed` without a re-init.
- **Tabular view, 2+ row fields**: `pivot-grid.js` renders every
  `response.columns` entry as a regular column — row fields are **not**
  collapsed into an auto-generated "Group" column. The Excel export
  mirrors the grid exactly.
- **View toggles**: hidable config panel and fullscreen result overlay
  live in `pivot.js` (`setConfigHidden`, `setFullscreen`) and CSS in
  `styles.css` (`.pivot-fullscreen`, `body.pivot-fullscreen-active`).
- **Phase 5 frontend split** (under `backend/app/static/js/`):
  - `drilldown-selection.js` (161 lines) builds the `selection` map
    that goes into `POST /api/pivot/drilldown`. Exposes
    `window.DrilldownSelection` with `buildSelectionForRow`,
    `buildSelectionList`, `getSelectedPivotRows`,
    `getCurrentPivotResponse`, and `dedupKey` — a stable JSON-string
    dedup key (keys sorted alphabetically, each `k=v` JSON-encoded)
    used by the merge loop to detect identical raw records.
  - `drilldown-manager.js` (~800 lines) is the modal orchestrator. It
    exposes `window.DrilldownManager` with
    `open / openForCurrentSelection / openForRow / close / hasData /
    getCurrentDataset / getCurrentContext / getVisibleColumns /
    getVisibleRows`. It owns the AG Grid instance, the toolbar
    (search + column visibility + reset + export), the summary
    card (Dataset / Sheet / Selected Pivot Rows / Matching /
    Returned), the matching-criteria card, the loading overlay with
    progress text (`"3 / 5 groups · Region=North"`), the friendly
    empty state, the dedup + merge loop, and a stable `inflightToken`
    that discards stale responses if the user opens a new drilldown
    while another is loading. It listens for `pivot:computed` (dispatched
    by `pivot.js`) to clear the cached dataset and for `theme:changed`
    to re-skin the grid wrapper.
  - `drilldown-export.js` (~170 lines) is a thin SheetJS wrapper for
    exporting the drill-down view. Exposes
    `window.DrilldownExport.exportCurrentView()` and the pure helper
    `buildWorkbookFromView(columns, rows, options)` that returns a
    SheetJS workbook. The pure helper is the **reusable form for
    Phase 6** — the email module can call it with the cached dataset
    (no backend round-trip) and ship the returned workbook as the
    email attachment.
- **Multi-row drill-down dedup strategy**:
  - Each fetched record is given a stable key by
    `DrilldownSelection.dedupKey(record)`:
    `Object.keys(record).sort().map(k => k+'='+JSON.stringify(record[k])).join('|')`.
  - A `Set` tracks which keys have been seen; the first occurrence of
    a key wins, subsequent occurrences are dropped.
  - `metadata.matched_rows` is the **additive** total (the sum of
    `matched_rows` across all drilldown calls — accurate, no dedup),
    so the user can see how many raw records the API found before
    dedup.
  - `metadata.returned_rows` is the **deduped** count (what's actually
    in the grid).
- **Email-phase reuse plan** (now realised in Phase 6):
  - `DrilldownManager.getCurrentDataset()` returns the merged
    `PivotDrilldownResponse` (rows + columns + metadata) already in
    memory.
  - `DrilldownManager.getVisibleColumns()` / `getVisibleRows()` return
    the user's current view (after column visibility + search + sort).
  - `DrilldownExport.buildWorkbookFromView(visibleColumns, visibleRows,
    {sheetName, filename})` returns a SheetJS workbook that can be
    attached to an email via
    `XLSX.write(wb, {type: 'array'})` → `new Blob([...], {type:
    'application/octet-stream'})` → SMTP attachment. **Zero backend
    round-trip** is needed for the attachment because the dataset is
    already cached.
- **Phase 6 frontend split** (under `backend/app/static/js/`):
  - `email-manager.js` is the Email Composer modal controller. It
    owns the To/CC/BCC/Subject/Message form, the recent-recipient
    typeahead, the Preview / Send / Reset buttons, and the iframe-
    rendered HTML preview. It reuses `DrilldownSelection` to build
    the `selections` list the server expects and `PivotAppState` /
    `PivotGrid.getLastResponse()` for the pivot context. The
    Send button is enabled only after Preview succeeds.
  - `preview-manager.js` is a thin wrapper that renders the server-
    built HTML inside a sandboxed iframe inside the composer.
  - `smtp-settings.js` is the SMTP settings page controller at
    `/email/settings` — load / save / send-test. The password
    field is always blank in the form (the server never returns
    the password; it returns `passwordSet: true/false`).
  - `email-history.js` is the history page controller at
    `/email/history` — list with search + status filter, clickable
    error messages, and re-download buttons for successful
    attachments.
- **Phase 6 HTML email body** is built in
  `email_service.build_email_html()`. Uses table-based layout +
  inline CSS for Outlook/Gmail compatibility. The body has:
  subject bar (blue) → user message → **pivot summary table**
  (selected rows + column headers) → "The detailed drill-down
  report is attached." → footer (Generated By / On / Dataset /
  Sheet). The **grand-total block is intentionally NOT rendered**
  — it was blank in V1 because the engine returns `totals.grand`
  keyed by value-label, not by column. The grand totals are still
  in the .xlsx attachment.
- **Phase 6 multi-row dedup** (server side): `pivot_service.
  build_drilldown_multi()` calls `build_drilldown` once per
  selection and merges the results using the same stable-JSON-key
  dedup as the drilldown modal. `metadata.matched_rows` is the
  additive total across calls; `metadata.returned_rows` is the
  post-dedup count. Both are returned to the client and stored
  in the email history row.
- **Phase 6 SMTP password storage**: plaintext in SQLite for V1
  (singleton row, internal tool). The schema column is isolated
  so a `cryptography.fernet` wrapper can be added in a future
  hardening pass without changing the API shape.
