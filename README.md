# Pivot App

**Excel Pivot Analysis + Stakeholder Mailing Platform**

An internal operational web app for uploading Excel/CSV datasets, extracting
reusable metadata, configuring pivots in the browser, and computing pivots on
the backend. Future phases will add export, scheduled reports and stakeholder
mailing.

## Recent Updates

| Commit    | Description                                                                                       |
| --------- | ------------------------------------------------------------------------------------------------- |
| (latest)  | `feat(directory-csv)`: User Directory now backed by two CSVs in the project root (`Users.csv` for individuals, `DistributionLists.csv` for groups) instead of a single `users.json`. Both are mounted read-only into the container; the email composer's typeahead merges both sources and shows a `User` / `Distribution list` badge per result (individuals rank above groups on a tie). New `kind` field on the `/api/users/suggest` response + new `kind` query-param to filter the search to one source. Settings page card now shows a separate count + file path + size for each source, plus a "Last loaded" IST timestamp. `app/services/user_directory.py` rewritten to parse CSV via the stdlib `csv` module, with mtime-based auto-reload per file and per-file `users` / `dls` counts in `status()` and the `reload` response. The two CSVs are gitignored and mounted in `docker-compose.yml`; env vars: `USERS_CSV_PATH`, `DISTRIBUTION_LISTS_CSV_PATH` (defaults: `/app/Users.csv`, `/app/DistributionLists.csv`). |
| (prev)    | `feat(email+tz)`: email default template + every timestamp in IST. The user's new default email body is `Hello Team,\n\nWe've been consistently receiving alerts related to the following issue types on a daily basis. Kindly investigate the root cause and take necessary action to resolve them permanently.\n\nRegards,` (no more "drill-down report is attached" footer line). Every visible timestamp in the app — email body, datasets list, preview, audit, log viewer, health endpoint, draft recovery banner, AG Grid export — is now formatted in **IST (Asia/Kolkata, UTC+5:30)**. New `tz.py` helper (`format_ist`, `iso_ist`, `now_ist`) on the backend; new `format.js` (`window.AppFormat.ist`) on the frontend. The default timezone in `app_settings` is now `Asia/Kolkata` (was `UTC`). Every API endpoint that returns a timestamp now also returns an `*_ist` field (ISO-8601 with the +05:30 offset) so the frontend never has to guess. |
| (prev)    | `fix(admin+email)`: Log Viewer 500 + Send Email stuck on "Sending…". The `/logs` page was passing `request=None` to `templates.TemplateResponse(...)` which threw `AttributeError: 'NoneType' object has no attribute 'get'` at render time — fixed by declaring a proper `Request` parameter on the route handler. The Send Email button was stuck on the "Sending…" spinner because the original label was only restored in the error branch — restructured to always restore the label in the `finally` block. Also hardened `email-manager.js` to handle non-JSON responses gracefully (the "JSON.parse: unexpected character" error). |
| (prev)    | `fix(email)`: Email Preview "JSON.parse: unexpected character" error. Two related bugs: (1) `main.py` exception handlers always returned the friendly HTML error page, even for `/api/*` requests — fixed to return `JSONResponse` when the path starts with `/api/`. (2) `PivotAppState()` was overwriting `payload.columns` with the full dataset column list — now exposed as a separate `availableColumns` field. |
| (prev)    | `fix(safety)`: extract `.selection` from `buildSelectionList` before sending to delete-records API. `DrilldownSelection.buildSelectionList()` returns `[{pivotRow, selection}]` but the API expected `[{field: value}]`. The wrapper object's keys (`pivotRow` / `selection`) never matched any DataFrame column, so `_apply_selection` silently skipped ALL filters and soft-deleted every row in the dataset. Fix: `.map(entry => entry.selection)` in pivot.js + backend safety net in `_apply_selection` that returns an empty DataFrame if no filter matched any column. Cache-bust bumped to `?v=5`. |
| (prev)    | `f6501e4` / `6fbafab` — **fix (safety, follow-up)**: bumped the JS cache-bust to `?v=4`. The user reported that the modal still showed "3,440 source record(s)" after rebuilding with `docker compose build --no-cache` — the live API returns `matched: 920` for the DISK SPACE selection, and the modal text the user pasted is from the NEW code, so the discrepancy was a stale browser cache. `?v=4` forces a fresh fetch of `pivot.js` on the next page load. Also removed the temporary `log_event()` debug calls from the dry-run endpoint. |
| (prev)    | `cf743c2` — **fix (safety)**: `Delete Records` on the Pivot page now runs a **dry-run preview** before the actual delete. The modal shows the actual **source-record count** that will be soft-deleted (not just the pivot row count), tags deletes > 500 records as `LARGE` and > 2000 as `HUGE` with explicit warnings, and disables the Confirm button if the count is 0. Prevents the "I selected 1 row but it deleted the entire dataset" failure mode when AG Grid's multi-row selection picks up more rows than the user expected. |
| (prev)    | `737cd93` / `7d2fc9c` — **fix (safety)**: the soft-delete selection was including **value columns** (e.g. `count_Key | 2026-06-29` from a date-grouped column) alongside the row field. The previous code only skipped keys that exactly matched the aggregation label, so column-grouped keys leaked through and the modal showed a noisy 8-key selection instead of the single `{Issue_Category: 'DISK SPACE'}` the user expected. `buildSelectionForRow` now strips every column-grouped key (any key containing `|`) and any key not in the configured `rowFields` set. Bumped the JS cache-bust to `?v=3` so a stale browser stops loading the old `pivot.js`. |
| (prev)    | `9f4524a` — **fix**: auto-scroll to the AG Grid on narrow viewports after clicking Compute Pivot, so the result is always visible without manual scrolling. `bb98627` — **fix**: cache-bust the pivot page JS files (`?v=2`) so a stale browser doesn't keep loading the old `pivot.js` / `pivot-grid.js` after a deploy. |
| (prev)    | **Phase 8 hotfix #3 — "deleted row reappears after refresh"**: the soft-delete service and the pivot engine each computed a per-row `source_key` SHA-256 for the soft-delete filter, but the two implementations drifted — the writer saw JSON `null` (drilldown response) and the reader saw `NaN` (pandas re-read), so the hashes never matched and every soft-deleted row leaked back into the next pivot. Fix: shared module `backend/app/services/row_keys.py` with a single `row_source_key()` helper that normalises every value (`None` / `NaN` / `NaT` / `''` all collapse to `None`; datetimes to ISO) before hashing. Regression test: `/tmp/jsm_api2.py` runs the user's exact 16-step scenario against the real JSM CSV and asserts the ZABBIX row is gone after a delete. |
| (prev)    | **Phase 8 hotfix #2 — "values are showing empty" after Delete Records refresh**: the AG Grid's `getRowId` was using every data key (including value columns) and the Phase 4 "reuse the existing instance" pattern silently lost columns on re-render. Fix: `buildRowId` now excludes value fields so the row ID is stable for the same pivot row across re-renders, and `render()` now destroys + recreates the AG Grid instance on every re-render (heavier but guaranteed to match the new columnDefs; user selection is preserved across the recreate). |
| (prev)    | **Phase 8 hotfix #1 — null/NaN pivot values**: default valueFormatter on every column now returns `"—"` for `null` / `undefined` / non-finite numbers (e.g. `average`/`min`/`max` on an empty group after a soft delete). |
| (prev)    | **Phase 8 — Production-ready hardening**: Application Settings page (`/settings`), `GET /health` endpoint, rotating-file logging + SQLite mirror + Log Viewer page (`/logs`), friendly 400/403/404/500 error pages, three-layer file validation (extension / MIME / magic bytes), runtime-configurable max upload size, Diagnostics page (`/diagnostics`), Admin Cleanup utility (`/admin/cleanup`), Delete Audit page (`/admin/audit`), **Delete Records** feature on the Pivot page with **soft delete** (records disappear from pivot / drill-down / exports / email attachments without changing the existing workflow), automatic pivot refresh after delete, in-process metadata cache with auto-invalidation, draft recovery (pivot config auto-saved to localStorage; restore banner on next page open), better loading overlays + double-click guard on every action button. |
| (prev)    | **Phase 7 — Excel-like pivot enhancements**: expand / collapse row groups, Repeat Item Labels (Tabular Form), real subtotal rows at the second-to-last row-field level, column totals pinned beneath the grand total, conditional formatting (gt / lt / eq / top 10 / bottom 10 / duplicates), number formatting (integer / decimal / currency / percentage / thousands), date formatting (yyyy-mm-dd / dd-mm-yyyy / MMM yyyy / MMMM yyyy / quarter / year), freeze columns, hide / show columns, auto-fit column widths, copy to clipboard (TSV → Excel), print view (title + dataset + table + totals + date), responsive polish. 16/16 manual tests pass. |
| (prev)    | **Phase 6 — Email composition**: Send Email button on the Pivot page → composer modal (To/CC/BCC + Subject + Message) with HTML preview, .xlsx attachment, SMTP settings page, email history page, recent-recipient autocomplete, and 11 new API endpoints. The grand-total block in the email body is disabled (it was rendering blank in V1) — the pivot summary table is still rendered. |
| (prev)    | **Phase 5 — Drill-down**: double-click or multi-select pivot rows → Bootstrap modal with raw records, dedup, search, column visibility, matching-criteria card, summary card, and reusable Excel export. |
| (prev)    | Add view controls on `/pivot`: hidable configuration panel + fullscreen pivot result overlay.     |
| (prev)    | Fix tabular view: row fields are now shown as their own columns (no auto "Group" column collapse). |
| `fa4b8ca` | Phase 4 implemented — Excel-like AG Grid result UI, Pivot Statistics, client-side Excel export.   |
| `f782c81` | Fix pivot grid: use `colDefs` (defined) instead of undefined `columnDefs` — AG Grid now renders.  |
| `7bfba51` | Fix bug: uploaded dataset not showing in pivot page dropdown (defensive init + lazy filter modal). |
| `e645b28` | Dark mode: fix black/grey text on white background contrast issues.                               |
| `705ef4e` | Phase 1-3 implementation + dark / light / system theme shipped.                                  |

For the full V1 release notes (architecture, folder structure, schema, API,
caching, soft-delete, logging, diagnostics, cleanup, deployment), see
[`VERSION_1_RELEASE.md`](./VERSION_1_RELEASE.md).

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
- **Excel-like pivot enhancements** (Phase 7) — 15 new behaviours that
  make the pivot feel close to a real Excel PivotTable:
  - **Expand / collapse row groups** — every group has a chevron
    (`▸`/`▾`) in a virtual pinned-left column. Click to toggle one
    group, or use **Expand All** / **Collapse All** in the action
    toolbar. Expansion state survives re-renders (via a client-side
    `Set<string>` of collapsed parent keys).
  - **Repeat Item Labels** (Tabular Form) — instead of showing blank
    grouped cells, the grouped value is repeated on every row. The
    backend fills the blanks on the fly (`totals.repeatItemLabels: true`)
    and the frontend styles the cell.
  - **Real subtotal rows** — `totals.showSubtotals: true` makes the
    backend insert a subtotal row after every group at the
    second-to-last row-field level (Excel's exact behaviour). For
    `rows = [Region, Product]` the subtotal sits at the Region level
    and shows the aggregated value of every value spec; the
    `Product` cell stays blank so the user sees a real Excel
    Subtotal line. The leaf rows are excluded from the subtotal
    re-aggregation so the numbers are correct for every
    aggregation (`sum`, `count`, `average`, `min`, `max`).
  - **Column totals** — `totals.showColumnTotals: true` makes the
    backend append a per-column-total row, **pinned beneath the
    grand total** in the same `pinnedBottomRowData` slot. The column
    total is the sum/min/max/avg of the **leaves only** — never of
    subtotals — so the column total is consistent with the per-row
    numbers and never double-counts.
  - **Conditional formatting** — add rules via a Bootstrap modal
    (`gt`, `lt`, `eq`, `top10`, `bottom10`, `duplicates`) and pick
    any background colour. The rules are evaluated on every render
    via `cellClassRules` and a CSS class is applied to matching
    cells. The top-N rules re-rank the column on every redraw and
    highlight the top/bottom 10%.
  - **Number formatting** — per-field dropdown (`integer`,
    `decimal`, `currency`, `percentage`, `thousands`). Driven by
    AG Grid `valueFormatter` — the value is formatted in place,
    no string round-trip, perfect for copying.
  - **Date formatting** — per-field dropdown (`yyyy-mm-dd`,
    `dd-mm-yyyy`, `MMM yyyy`, `MMMM yyyy`, `quarter`, `year`).
  - **Freeze columns** — pin any column to the left edge of the
    grid via the **Freeze** dropdown. Backed by AG Grid
    `pinned: 'left'`. The user's choice is stored in
    `appState.displayOptions.frozenColumns`.
  - **Hide / show columns** — toggle column visibility via the
    **Columns** dropdown (or the **Reset** button to restore
    everything). Backed by `hide: true` + `setColumnsVisible`.
  - **Auto-fit column widths** — **Auto-fit all columns** resizes
    every visible column to fit its widest cell
    (`sizeColumnsToFit`); **Auto-fit current page** resizes only
    the currently visible columns (`autoSizeColumn`).
  - **Copy to clipboard** — three modes: **Selected cells** (TSV of
    the current AG Grid cell range), **Selected rows** (TSV of
    every selected row), **Selected rows with headers** (TSV of
    every selected row + a header row). Uses
    `navigator.clipboard.writeText` with a `document.execCommand`
    fallback. Pastes cleanly into Excel, Numbers, and Google
    Sheets.
  - **Print view** — clicking **Print** builds a hidden
    `#pivotPrintView` with a clean, professional layout: title
    (Dataset + Sheet), date generated, the pivot table with
    subtotal/grand-total styling, and the grand total pinned to
    the bottom. The print stylesheet (`@media print`) hides
    everything on the page and shows only the print view; the
    user gets a paper-ready printout.
  - **Responsive / sticky polish** — the action toolbar is
    `sticky-top` and now includes a "Row groups" button group
    (Expand / Collapse All) and a "Grid actions" group
    (Columns / Freeze / Reset / Auto-fit / Copy / Print). The
    Phase 7 Display Options card sits in the left config panel
    under the existing Layout & Totals card.
  - **Performance** — the grid instance is reused across re-renders
    (`setGridOption` instead of `destroy` + `createGrid`). State
    changes that need a cell re-evaluation call
    `refreshCells({ force: true })` instead of rebuilding the
    columns, so the user's column widths, sort state, and
    column visibility are preserved.
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
│   │   │   ├── column.py
│   │   │   ├── smtp_settings.py         ← Phase 6
│   │   │   ├── email_history.py         ← Phase 6
│   │   │   └── recent_recipient.py      ← Phase 6
│   │   ├── repositories/
│   │   │   ├── __init__.py
│   │   │   ├── dataset_repository.py
│   │   │   ├── sheet_repository.py
│   │   │   ├── column_repository.py
│   │   │   ├── smtp_settings_repository.py    ← Phase 6
│   │   │   └── email_history_repository.py    ← Phase 6
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── upload_routes.py
│   │   │   ├── dataset_routes.py
│   │   │   ├── pivot_routes.py
│   │   │   └── email_routes.py          ← Phase 6 — 11 endpoints
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── dataset.py
│   │   │   ├── pivot.py                 ← Phase 7 — DisplayOptions + ConditionalFormat
│   │   │   └── email.py                 ← Phase 6
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── excel_service.py
│   │   │   ├── dataset_service.py
│   │   │   ├── pivot_service.py         ← Phase 7 — subtotals, column totals, repeat labels, hierarchy markers
│   │   │   ├── pivot_validation_service.py ← Phase 7 — validates display options
│   │   │   ├── attachment_service.py     ← Phase 6 — builds the .xlsx
│   │   │   ├── smtp_service.py           ← Phase 6 — smtplib wrapper
│   │   │   ├── email_service.py          ← Phase 6 — orchestrator + HTML
│   │   │   └── email_history_service.py  ← Phase 6 — read-side
│   │   ├── static/
│   │   │   ├── css/styles.css            ← Phase 7 — subtotal/column-total/print styles
│   │   │   └── js/
│   │   │       ├── theme.js              ← light / dark / system theme switcher
│   │   │       ├── upload.js
│   │   │       ├── manage.js
│   │   │       ├── pivot.js              ← controller (~1300 lines — Phase 7 wires Display Options, columns/freeze menus, auto-fit/copy/print)
│   │   │       ├── pivot-grid.js         ← AG Grid wrapper (Phase 4 + 7 — expand/collapse, subtotals, conditional formats, freeze/hide, auto-fit, copy, print)
│   │   │       ├── pivot-display.js      ← Phase 7 — Display Options controller (number/date format, conditional formatting, freeze/hide, auto-fit, copy, print)
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
│   │   │   ├── pivot.html                ← Phase 7 — Display Options card, expand/collapse, columns/freeze/auto-fit/copy/print toolbar, conditional-formatting modal, print view
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
├── Phase5
├── Phase6
├── Phase7                              ← Excel-like enhancements
└── README.md
```

### Frontend module split (`backend/app/static/js/`)

| File | Role |
| --- | --- |
| `pivot.js`              | Controller — owns `appState`, left config panel, `buildPayload()`, validate / compute flow, stats panel, selection bar, search input, export + drill-down + email orchestration, view toggles (hide config / fullscreen), defensive `try { main() } catch` init, lazy filter modal, theme listener. Exposes `window.PivotAppState()` for the drilldown / email managers (and the Phase 7 display-options dropdowns, which need the full dataset column list). Dispatches `pivot:computed` after every successful compute. Phase 7 additions: extends `appState` with `displayOptions` + `totals.repeatItemLabels`; wires **Expand All / Collapse All**, the **Columns** / **Freeze** / **Auto-fit** / **Copy** / **Print** dropdowns; **syncDisplayOptionsFromUI()** mirrors the live state from `PivotDisplay` into `appState.displayOptions` so the next payload carries every Phase 7 option; the **Display Options** card hooks every `change` + `click` event so the sync is automatic. |
| `pivot-grid.js`         | Pure AG Grid wrapper for the **pivot result**. Exposes `window.PivotGrid` with `render / clear / getSelectedRows / getSelectedCount / getSelectedGroups / getTotalRowCount / selectAll / clearSelection / setSearchTerm / getVisibleColumns / getVisibleRows / getLastResponse / getLastContext / setColumnsVisible / setColumnPinned / autoSizeAllColumns / autoSizeSelectedColumn / copySelection / printView / expandAll / collapseAll / expandGroup / collapseGroup / toggleGroup`. Phase 7 adds the expand/collapse state machine (a `Set<string>` of collapsed parent keys), the virtual `__pivot_toggle` column (chevron in the pinned-left section), `valueFormatter` for number / date formats, `cellClassRules` for conditional formats, the **column-total pinned row** in `pinnedBottomRowData`, `refreshCells({ force: true })` after every state change, and the document-level click delegate that fires the chevron toggle (AG Grid 31's `onCellClicked` doesn't fire for pinned-left cells). The `render()` context now supports Phase 5 (`onRowDoubleClick`) AND Phase 6 (`onSelectionChange`) callbacks — unchanged. |
| `pivot-display.js`      | **Phase 7** — Display Options controller. Owns the **Display Options** left-panel card (Repeat Item Labels, Number Format, Date Format, Conditional Formatting, Freeze Columns, Hide Columns, Auto-fit, Copy, Print, Reset). Public API: `init / reset / getState / applyToGrid / getAvailableFields / setAvailableFields / getFrozenColumns / getHiddenColumns / getNumberFormats / getDateFormats / getConditionalFormats`. State is stored on the DOM widgets; `getState()` returns a fresh copy on every call so the controller's payload builder always sees the latest values. |
| `pivot-export.js`       | SheetJS export of the **pivot result**. Exposes `window.PivotExport.exportCurrentView()` and `setNotifier()`. Mirrors what the user sees in the grid (visible columns in display order, current sort, current filter, the grand-total pinned row). |
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
| `/email/settings` | SMTP configuration (Phase 6) |
| `/email/history`  | Sent emails (Phase 6) |
| `/settings` | Application settings (Phase 8) — name, company, timezone, max upload size |
| `/diagnostics` | System diagnostics — application, database, storage, SMTP, folders (Phase 8) |
| `/logs`     | Log Viewer — search / filter / download the application log (Phase 8) |
| `/admin/cleanup` | Admin Cleanup utility — preview + delete temp exports, old logs, orphans (Phase 8) |
| `/admin/audit`   | Delete Audit — every soft-delete operation with criteria + counts (Phase 8) |
| `/health`   | JSON health endpoint for Docker / monitoring (Phase 8) |
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

### Phase 4 — Pivot compute

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

### Phase 5 — Drilldown

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

### Phase 7 — Excel-like pivot enhancements (request contract only)

Phase 7 extends the existing `POST /api/pivot/validate` and `POST /api/pivot`
endpoints with two new top-level fields on the request — no new endpoints are
added. The full request shape is:

```jsonc
{
  "datasetId":      1,
  "sheetName":      "Sheet1",
  "rows":           ["Region", "Product"],
  "columns":        [],
  "values":         [{"field": "Sales", "aggregation": "sum", "label": "sum_Sales"}],
  "filters":        {},
  "dateGrouping":   {},
  "sorting":        {},
  "layout":         "tabular",
  "totals": {
    "showGrandTotals":     true,
    "showRowTotals":       true,
    "showColumnTotals":    false,
    "showSubtotals":       false,
    "repeatItemLabels":    false   // ← Phase 7
  },
  "displayOptions": {            // ← Phase 7 (whole block is new)
    "numberFormat": { "sum_Sales": "currency" },
    "dateFormat":   { "Date":      "yyyy-mm-dd" },
    "conditionalFormats": [
      {"field": "sum_Sales", "type": "gt",         "value": 100, "background": "#ffd966"},
      {"field": "sum_Sales", "type": "lt",         "value": 50,  "background": "#ffaaaa"},
      {"field": "sum_Sales", "type": "top10",      "background": "#aaffaa"},
      {"field": "sum_Sales", "type": "bottom10",   "background": "#aaaaff"},
      {"field": "sum_Sales", "type": "duplicates", "background": "#ffaaff"}
    ],
    "frozenColumns": ["Region"],
    "hiddenColumns": []
  }
}
```

- `totals.repeatItemLabels` — when `true`, the backend fills the blank
  row-field cells with the value from the row above (Excel Tabular
  Form). The subtotal rows' deepest level is intentionally left
  blank.
- `totals.showSubtotals` — when `true`, the backend inserts a real
  subtotal row at the second-to-last row-field level after every
  group change. Subtotal rows are re-aggregated from the leaf
  rows in the group (correct for `sum`, `count`, `average`, `min`,
  `max`).
- `totals.showColumnTotals` — when `true`, the backend appends a
  per-column-total row, **pinned beneath the grand total** in the
  same `pinnedBottomRowData` slot. The column total is computed
  from the leaves only (never from subtotals) so it never
  double-counts.
- `displayOptions.numberFormat` — `{ field: "integer" | "decimal" |
  "currency" | "percentage" | "thousands" }`. Applied to the
  matching value / row-field column. Other formats are ignored
  (validation error if the value is unknown).
- `displayOptions.dateFormat` — `{ field: "yyyy-mm-dd" | "dd-mm-yyyy" |
  "MMM yyyy" | "MMMM yyyy" | "quarter" | "year" }`.
- `displayOptions.conditionalFormats` — list of rules. `type` is
  one of `gt | lt | eq | top10 | bottom10 | duplicates`. `gt` /
  `lt` / `eq` require a numeric `value`; `top10` / `bottom10` /
  `duplicates` ignore it. `background` is an optional CSS
  colour (defaults to `#ffd966`).
- `displayOptions.frozenColumns` — array of column names; the
  matching columns are pinned to the left edge of the grid.
- `displayOptions.hiddenColumns` — array of column names; the
  matching columns are hidden in the result.

Every response row is annotated with hierarchy markers so the
frontend can drive expand / collapse and subtotal styling without
recomputing anything:

```jsonc
{
  "Region":   "North",
  "Product":  "A",
  "sum_Sales": 100,
  "__level":      1,        // 0..N — 0 = top-most group
  "__parentKey":  "North"   // joined values of all parent row fields
}
{
  "Region":   "North",
  "Product":  "",
  "sum_Sales": 300,
  "__isSubtotal": true,
  "__level":      0,
  "__parentKey":  "North"
}
{
  "__isGrandTotal":   true,
  "Region":     "Grand Total",
  "sum_Sales":  1090
}
{
  "__isColumnTotal":  true,
  "Region":     "Column Total",
  "sum_Sales":  1090
}
```

**Backward compatibility** — every new field has a default that
preserves the Phase 1-6 behaviour. Existing clients that send no
`displayOptions` see exactly the same response as before
(modulo the harmless `__level` / `__parentKey` markers on every
row, which the existing frontend ignores).

The validation endpoint `POST /api/pivot/validate` also accepts
`displayOptions` and returns the per-field errors / warnings.

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

| Column                   | Type     | Description                                                                |
| ---                      | ---      | ---                                                                        |
| `id`                     | INTEGER  | Primary key                                                                |
| `sent_at`                | DATETIME | Send timestamp                                                             |
| `subject`                | TEXT     | Email subject                                                              |
| `to_addresses_json`     | TEXT     | JSON array of To addresses                                                 |
| `cc_addresses_json`     | TEXT     | JSON array of CC addresses                                                 |
| `bcc_addresses_json`    | TEXT     | JSON array of BCC addresses                                                |
| `dataset_id`             | INTEGER  | FK → `datasets.id` (informational)                                        |
| `dataset_name`           | TEXT     | Original upload filename                                                  |
| `sheet_name`             | TEXT     | Sheet the pivot was built from                                             |
| `pivot_rows_count`       | INTEGER  | Number of pivot rows the user sent                                         |
| `attached_records_count` | INTEGER  | Number of records in the .xlsx (post-dedup)                                |
| `status`                 | TEXT     | `success` or `failed`                                                      |
| `error_message`          | TEXT     | Failure reason (NULL on success)                                           |
| `attachment_filename`    | TEXT     | The .xlsx filename (e.g. `Pivot_Drilldown_2026-06-30_14-30.xlsx`)         |
| `attachment_path`        | TEXT     | Relative path under `REPORTS_DIR/email_attachments/`                        |
| `pivot_payload_json`     | TEXT     | JSON snapshot of the request — lets the history page re-render the email body without re-querying the dataset |

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

### Phase 7 — Excel-like pivot enhancements

All 16 tests below were verified end-to-end with a headless
Playwright run against the deployed build (see
`/tmp/pivot-phase7-final.png` for the rendered page after the run).

1. **Expand one group** — with a 2-row-field pivot (Region + Product),
   collapse all, then click the chevron in the first subtotal row's
   toggle cell. Only that group's detail rows appear; the rest stay
   collapsed. Expected: the East detail rows are visible, the
   North / South / West subtotals remain alone.
2. **Collapse one group** — click the chevron again (now showing `▾`).
   The detail rows hide, leaving just the subtotal. Expected: only
   the four region subtotals visible.
3. **Expand All** — with everything collapsed, click the **Expand All**
   button in the action toolbar. Expected: every leaf row + every
   subtotal is visible.
4. **Repeat Item Labels** — enable **Layout & Totals → Repeat Item
   Labels** and re-generate. The first column of every detail row
   should show the Region name, never a blank cell.
5. **Subtotals** — enable **Layout & Totals → Show Subtotals** and
   re-generate with 2+ row fields. Expected: a subtotal row appears
   after every group change at the second-to-last level. Each
   subtotal is bold-tinted, and its deepest-level cell is blank
   (so the user sees an Excel "Subtotal" line).
6. **Column totals** — enable **Layout & Totals → Show Column Totals**.
   Expected: a `Column Total` row appears beneath the grand total,
   pinned at the bottom, with a yellow tint. The value is the sum /
   min / max / avg of the **leaves only** (never of the subtotals,
   so the column total never double-counts).
7. **Conditional formatting** — open the **Manage Rules** modal,
   pick `sum_Sales` + `gt` + `150` + a colour, click **Add rule**.
   The cells where `sum_Sales > 150` should now be highlighted.
8. **Number formatting** — add `sum_Sales` → `currency` to the
   Number Format list. Expected: the column renders as `$1,090`
   instead of `1090`. Format is applied in place via AG Grid
   `valueFormatter`; copying still produces a numeric value.
9. **Date format** — add `Date` → `yyyy-mm-dd` to the Date Format
   list. Expected: any date values in the `Date` column render
   in the chosen format.
10. **Freeze first column** — open the **Freeze** dropdown in the
    action toolbar, check **Region**. Expected: a pinned-left
    container appears, and `Region` stays visible while the user
    scrolls horizontally.
11. **Hide and restore columns** — open the **Columns** dropdown,
    uncheck **Product**. Expected: the Product column disappears.
    Click **Reset** to restore.
12. **Auto-fit columns** — open the **Auto-fit** dropdown, click
    **Auto-fit all columns**. Expected: every column width
    adjusts to its widest cell. No errors in the console.
13. **Copy rows** — select a few rows, open the **Copy** dropdown,
    click **Selected rows with headers**. Paste into Excel.
    Expected: a TSV table appears with a header row + the
    selected rows in tab-separated form.
14. **Print preview** — click **Print**. Expected: the print
    stylesheet hides the entire page and shows only the print
    view (title + dataset + table + totals + date). The print
    dialog opens.
15. **Large dataset performance** — re-compute the pivot with no
    subtotals (flat view). Expected: the grid renders all rows
    in under a second; the user can scroll, search, and copy
    without lag.
16. **Review UI** — open the **Display Options** card. Expected:
    clean Bootstrap form with every Phase 7 control visible;
    no console errors; the action toolbar shows the Expand /
    Collapse All group + the Columns / Freeze / Auto-fit / Copy /
    Print group. The toolbar is sticky and the result area is
    scrollable.

## Known Issues / Lessons Learned

The codebase has hit a few subtle bugs that are now fixed. If you're
modifying the pivot grid (`backend/app/static/js/pivot-grid.js`),
the pivot engine (`backend/app/services/pivot_service.py`), or the
pivot page (`backend/app/static/js/pivot.js` + `pivot.html`), please
read this section first.

### AG Grid v31.3.2 — "values are showing empty" after a Delete Records refresh

**Symptom**: after clicking **Delete Records** and the auto-refresh
fires, the value column (`sum_Amount`, etc.) disappears from the grid
entirely. The data is correct in the API response and in
`PivotGrid.getLastResponse()`, but the rendered grid only shows the
row-field column. The user reported "values are showing empty" on
the pivot page.

**Two underlying causes** (both required the same fix):

1. **`getRowId` used every data key** — including the value columns.
   When the pivot was re-computed, the value field's number changed,
   the row ID changed, and AG Grid treated the row as new.

2. **`setGridOption("columnDefs", ...)` can silently drop columns on
   re-render** — in AG Grid v31, when the new columnDefs differ in
   shape from the previous ones, `getColumns()` correctly reports
   the new columns but the rendered DOM is missing one of them.

**Fix** (in `backend/app/static/js/pivot-grid.js`):

- `buildRowId` now excludes every value field (read from
  `lastResponse.aggregations[i].label` + the row_total_field), the
  `__*` markers, `_warning`, `Rows`, and `row_total`. The row ID is
  determined by the row fields + the marker flags, never by the
  aggregated numbers.
- `render()` now **destroys and recreates the AG Grid instance** on
  every re-render. This is heavier than the Phase 4 "reuse the
  existing instance" pattern (~few hundred ms for the typical
  pivot) but it guarantees the rendered grid exactly matches the
  new columnDefs. The user's selection is preserved across the
  recreate (saved before destroy via `buildRowId`, re-applied
  after).
- The grid-creation logic is extracted to `_createGrid()` so both
  the first-render and the destroy+recreate paths share it.
- A default valueFormatter is installed on every column that returns
  `"—"` for `null` / `undefined` / non-finite numbers — this covers
  the empty-group edge case (e.g. `average` / `min` / `max` on an
  empty group after a soft delete, which produces `NaN` →
  `null` in JSON).

**Regression test**: `/tmp/d3_test.py` is a headless-Playwright test
that reproduces the exact user scenario (one pivot row, delete,
auto-refresh, inspect the rendered grid). Both columns must be
present and the value column must show the correct post-delete
number. Keep this test around and re-run it whenever touching the
grid re-render path.

### AG Grid v31 deprecation warning

`api.setColumnPinned(key, pinned)` should be `api.setColumnsPinned([key], pinned)`.
Not broken yet but emits a console warning.

### Soft-delete row key — writer and reader must share a hash function

**Symptom**: after clicking **Delete Records**, the pivot recomputes
but the deleted row reappears. Confirmed with the user's exact
16-step scenario from `test` (against the real JSM CSV with 3440
rows, deleting the ZABBIX ROBI-BD-RBT ivrbd01 row with row_total=222):

```
BEFORE: 620 rows, 1 ZABBIX ROBI-BD-RBT ivrbd01 (row_total=222)
Delete: matched=222, deleted=222  ← delete claims success
AFTER:  620 rows, 1 ZABBIX ROBI-BD-RBT ivrbd01  ← row is BACK
```

**Root cause**: the soft-delete service (writer) and the pivot
engine's `_load_dataset_sheet` (reader) each computed a per-row
SHA-256 `source_key` for the soft-delete filter, but the two paths
disagreed on how to serialise empty cells:

- the writer received rows from the drilldown JSON response, where
  empty cells come back as JSON `null` → Python `None`
- the reader re-read the source file with pandas, where empty cells
  become `NaN` (float)
- `json.dumps(..., default=str)` on `None` → `"null"`
- `json.dumps(..., default=str)` on `NaN` → `"NaN"`
- the hashes never matched → every soft-deleted row was re-included
  in the next pivot compute

**Fix** (new shared module `backend/app/services/row_keys.py`):

- Single `row_source_key(row)` helper used by both the soft-delete
  service and the pivot engine
- Normalises every value before hashing: `None` / `NaN` / `NaT` /
  `''` all collapse to `None`; datetimes to ISO string;
  everything else as-is
- Now the writer and reader always produce the same hash for the
  same underlying row, regardless of whether it came from a JSON
  response or a pandas DataFrame

**Regression test**: `/tmp/jsm_api2.py` runs the user's exact
16-step scenario against the real JSM CSV via FastAPI TestClient
and asserts that AFTER a delete, the ZABBIX row is gone (0 matches)
and the audit log shows success. After the fix:

```
BEFORE: 620 rows, 1 ZABBIX ROBI-BD-RBT ivrbd01 (row_total=222)
Delete: matched=222, deleted=222
AFTER:  619 rows, 0 ZABBIX ROBI-BD-RBT ivrbd01  ← FIXED
```

Keep this test around and re-run it whenever touching the soft-delete
or row-keys code.

### `buildSelectionList` returns wrapper objects, not flat maps — Delete Records soft-deletes ALL rows

**Symptom**: clicking **Delete Records** on a single pivot row
soft-deleted *every* row in the dataset, not just the rows
contributing to the selected pivot row. The dry-run preview also
showed `matched = total source rows` regardless of the selection.

**Root cause**: `DrilldownSelection.buildSelectionList()` returns
`[{pivotRow: {…}, selection: {field: value}}]` (a list of wrapper
objects) but the delete-records API expects a flat list of
`{field: value}` maps. The old code sent the full wrapper to
`/api/pivot/delete-records`, so the backend's `_apply_selection()`
iterated over the wrapper object's keys (`pivotRow`, `selection`)
— neither exists as a column in the DataFrame, so every filter was
silently skipped and every row was returned (and soft-deleted).

**Fix** (two layers, frontend + backend safety net):

1. **Frontend** (`pivot.js`):
   ```js
   DrilldownSelection.buildSelectionList(dataRows, lastResponse)
     .map(entry => entry.selection || {})
   ```
   Extract the flat selection map from each `buildSelectionList`
   entry before sending to the API.

2. **Backend** (`pivot_service.py`): `_apply_selection()` now tracks
   whether any filter was actually applied; if a non-empty
   selection has **zero** fields matching any DataFrame column, it
   returns an **empty DataFrame** instead of all rows. This prevents
   the same class of bug from causing data loss even if the
   frontend sends the wrong shape again.

### API error pages must return JSON for `/api/*` endpoints — "JSON.parse: unexpected character"

**Symptom**: clicking **Preview** in the email composer (without a
recipient) showed `Preview failed: JSON.parse: unexpected character
at line 1 column 1 of the JSON data`.

**Root cause**: `main.py`'s 400 / 404 / 500 exception handlers always
returned the friendly HTML error page, even for `/api/*` requests.
The frontend's `fetch().json()` then tried to parse an HTML body
as JSON, threw the cryptic "JSON.parse" error, and the user had no
way to know what actually went wrong.

**Fix**: in `main.py`, the 400 / 404 / 500 handlers now check
`request.url.path.startswith("/api/")` and return a
`JSONResponse({"detail": "..."})` instead of the HTML page. The
friendly HTML page is preserved for browser navigation. Also
hardened `email-manager.js` to fall back to a meaningful error
message (`Server returned 400 (non-JSON): <snippet>`) if a future
bug ever returns a non-JSON body again.

### `PivotAppState()` must not overwrite `payload.columns`

**Symptom**: email Preview was failing in some configurations.

**Root cause**: `PivotAppState()` was overwriting `payload.columns`
(which `buildPayload` correctly set to `appState.columnsGroup`)
with the full list of dataset column names. The `EmailSendRequest`
schema treats `columns` as pivot column fields; sending every
dataset column could trigger unexpected behaviour downstream.

**Fix**: expose the full column list as a separate
`availableColumns` field on the payload, not by mutating
`columns`. The Phase 7 Display Options dropdowns read
`availableColumns`; the email endpoint sees the correct (small)
list of pivot column fields.

### Log Viewer 500 — `request=None` passed to `TemplateResponse`

**Symptom**: visiting `/logs` returned the 500 error page with
`AttributeError: 'NoneType' object has no attribute 'get'`.

**Root cause**: `log_routes.logs_page()` declared no `Request`
parameter and explicitly passed `"request": None` to
`templates.TemplateResponse(...)`. Starlette's template rendering
reads `request.get("extensions", {})` at render time, which threw
on `None`.

**Fix**: declare a proper `Request` parameter on the route handler
so the real ASGI scope is passed in.

### Send Email button stuck on "Sending…"

**Symptom**: clicking **Send** dispatched the email successfully
(the user received it) but the button label stayed on the
"Sending…" spinner forever.

**Root cause**: `onSend` replaced the button's `innerHTML` with a
spinner but only restored the original label in the **error**
branch. The success path set `disabled = true` and forgot to
restore the label. Additionally, the whole handler was wrapped in
`if (dom.sendBtn) { ... return; }` which silently swallowed clicks
when the button ref was missing.

**Fix**: restructured `onSend` so the original label is always
restored in the `finally` block, regardless of success / error /
exception. Removed the silent `if (dom.sendBtn) { ... return; }`
wrapper — a missing button now shows a clear error message. Also
invalidates `lastPreview` on success so a second send requires a
fresh preview.

### Log Viewer count was always 0

**Symptom**: the Log Viewer rendered rows correctly but the
`resultCount` always showed `0 record(s)`.

**Root cause**: `logs.js` was reading `data.count` but the
`/api/logs` endpoint returns `{rows: [...]}` (no `count` field).

**Fix**: use `data.rows.length` instead of `data.count`.

## How the theme system works

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

### Phase 1 — Upload & preview

1. Open `/` and the upload form should be visible.
2. The page should describe the supported file types (`.xlsx`, `.csv`).
3. Upload a normal `.xlsx` → confirm redirect to `/preview/{id}`.
4. Upload a `.csv` → confirm preview generates correctly.
5. Upload a `.pdf` → confirm `400` with a clear message.
6. Upload an empty `.xlsx` → confirm `422` with a clear message.
7. Upload a multi-sheet `.xlsx` → confirm all sheets are listed.
8. Restart the app → confirm previously uploaded files still exist.
9. Check the database (3 tables: `datasets`, `dataset_sheets`, `dataset_columns`).
10. Verify the preview table shows only the first 20 rows.
11. Run `docker compose config` to validate the compose file.

### Phase 2 — Dataset management

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

### Phase 3 — Pivot configuration

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

### Phase 4 — Pivot result UI

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

### Phase 7 — Excel-like pivot enhancements

1. **Expand / collapse row groups** — with a 2-row-field pivot,
   collapse all, then click the chevron in a row. The state
   is preserved across re-renders (uses a client-side
   `Set<string>` of collapsed parent keys). Use the
   **Expand All** / **Collapse All** buttons in the action
   toolbar for one-shot operations.
2. **Repeat Item Labels** — toggle **Layout & Totals → Repeat
   Item Labels**. The grouped value is repeated on every row
   instead of leaving the second / third row field blank. The
   backend fills the blanks; the frontend styles the cell.
3. **Subtotals** — toggle **Layout & Totals → Show Subtotals**.
   A real subtotal row is inserted at the second-to-last
   row-field level after every group change. For two row fields
   `[Region, Product]` the subtotal sits at the Region level
   with the Product cell blank. Subtotals are re-aggregated
   from the leaf rows so they're correct for every
   aggregation.
4. **Column totals** — toggle **Layout & Totals → Show Column
   Totals**. A `Column Total` row appears pinned beneath the
   grand total. The value is the sum / min / max / avg of the
   **leaves only** so the column total never double-counts.
5. **Conditional formatting** — open the **Manage Rules**
   modal from the Display Options card. Pick a field, a rule
   type (`gt` / `lt` / `eq` / `top10` / `bottom10` / `duplicates`),
   a value (where applicable), and a background colour. Click
   **Add rule** to apply. Rules are evaluated on every render
   via AG Grid `cellClassRules`.
6. **Number formatting** — pick a field in the Number Format
   list and a format (`integer` / `decimal` / `currency` /
   `percentage` / `thousands`). Driven by AG Grid
   `valueFormatter`.
7. **Date formatting** — same workflow for dates with the
   six supported formats (`yyyy-mm-dd` / `dd-mm-yyyy` /
   `MMM yyyy` / `MMMM yyyy` / `quarter` / `year`).
8. **Freeze columns** — open the **Freeze** dropdown in the
   action toolbar, check the columns you want pinned to the
   left. The pinned column is rendered in the `pinned-left`
   container; horizontal scroll keeps it visible. **Unfreeze
   all** removes all pins.
9. **Hide / show columns** — open the **Columns** dropdown,
   uncheck the columns you want to hide. **All** / **None**
   shortcuts. Click **Reset** to restore.
10. **Auto-fit column widths** — open the **Auto-fit**
    dropdown, click **Auto-fit all columns** to resize every
    visible column. Or **Auto-fit current page** to resize
    only the currently visible columns.
11. **Copy rows** — select one or more rows, open the
    **Copy** dropdown, pick **Selected cells** / **Selected
    rows** / **Selected rows with headers**. The TSV is
    written to the clipboard and pastes cleanly into Excel.
12. **Print view** — click **Print**. The print stylesheet
    hides every other element on the page and shows only
    the print view: title (Dataset + Sheet), date generated,
    the pivot table with subtotal / grand-total styling, and
    the grand total pinned to the bottom. The print dialog
    opens.
13. **Responsive / sticky polish** — the action toolbar is
    `sticky-top` and includes two new button groups:
    **Row groups** (Expand / Collapse All) and **Grid
    actions** (Columns / Freeze / Reset / Auto-fit / Copy /
    Print). The Display Options card sits in the left config
    panel under the existing Layout & Totals card.
14. **Performance** — the grid instance is reused across
    re-renders (`setGridOption` instead of `destroy` +
    `createGrid`). State changes that need a cell
    re-evaluation call `refreshCells({ force: true })` so
    the user's column widths, sort state, and column
    visibility are preserved. Large result sets remain
    responsive.
15. **UI polish** — the Display Options card and the action
    toolbar use the existing theme tokens; nothing is
    hard-coded. Subtotal rows have a light-grey background,
    column totals have a yellow background, grand totals
    have a green background — all theme-aware.
16. **Review the code** — Phase 7 is split into:
    - `pivot_service.py` — subtotal insertion
      (`_insert_subtotal_rows`), column total
      (`_insert_column_total_row`), repeat labels
      (`_apply_repeat_item_labels`), hierarchy markers
      (`_annotate_hierarchy`)
    - `pivot-display.js` — Display Options controller
      (number/date/conditional formats, freeze/hide, auto-fit,
      copy, print)
    - `pivot-grid.js` — AG Grid integration (expand/collapse
      state machine, the virtual `__pivot_toggle` column,
      `valueFormatter` + `cellClassRules`, pinned-bottom column
      total row, document-level chevron click delegate)
    - `pivot.js` — wires the Display Options card and the
      action toolbar; `syncDisplayOptionsFromUI()` mirrors
      the live state into `appState.displayOptions` for the
      next payload
    - `styles.css` — Phase 7 row classes
      (`pivot-subtotal-row`, `pivot-subtotal-cell`,
      `pivot-column-total-row`, `pivot-toggle-cell`,
      `pivot-toggle-chevron`) and the `@media print` rule

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
- **Phase 7 — grid performance:** the AG Grid instance is reused across
  every re-render (no `destroy` + `createGrid` round-trip). Expand /
  collapse state changes call `refreshCells({ force: true })` instead of
  rebuilding the columns, so the user's column widths, sort state, and
  column visibility are preserved. Large result sets (10 000+ rows)
  remain responsive; the top-N conditional-format rules re-rank the
  column on every render (cached in the future — see Implementation
  Notes below).
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
