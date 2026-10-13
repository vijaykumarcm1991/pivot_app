# Pivot App

An internal web app for analysing Excel / CSV data with pivot tables and
emailing the results to stakeholders.

Upload a workbook, build a pivot in the browser (computed on the backend
with pandas), then drill into the records behind any row, export to Excel,
email selected rows with the records attached, or soft-delete records with
a full audit trail.

## Features

- **Upload** `.xlsx` / `.csv` (multi-sheet), with extension / MIME /
  magic-byte validation and automatic column type detection.
- **Pivot Builder** — rows, columns, values (sum / average / count / min /
  max), filters, date grouping (day → year), sorting, tabular or compact
  layout, grand / row / column totals and subtotals.
- **Result grid** (AG Grid) — search, expand / collapse groups, freeze /
  hide columns, number / date / conditional formatting, copy, print,
  Excel export.
- **Drill-down** into the source records of one or more pivot rows.
- **Email** selected pivot rows via SMTP with an `.xlsx` attachment of the
  matching records; recipient typeahead from `Users.csv` /
  `DistributionLists.csv`; sent history with re-download.
- **Delete Records** — soft-deletes the records behind selected rows (the
  uploaded file is never modified), with a dry-run count and an audit log.
- **Admin** — settings (app name, timezone, upload limit), diagnostics,
  log viewer, delete audit, cleanup utility, `/health`.
- Light / dark / system theme; responsive layout.

## Tech stack

FastAPI (Python 3.11) · pandas + openpyxl · SQLite (SQLAlchemy) · Jinja2 +
Bootstrap 5 + vanilla JS · AG Grid Community · Docker Compose + Nginx.

## Getting started

### Docker (recommended)

```bash
./build_start.sh
```

Open <http://localhost:5000>.

The email typeahead reads `Users.csv` and `DistributionLists.csv` from the
project root (mounted read-only; changes are picked up automatically).
`build_start.sh` creates empty placeholders if they're missing — if you run
`docker compose up` directly, create both files first.

Expected headers:

```text
Users.csv              "DisplayName","PrimarySmtpAddress","Alias"
DistributionLists.csv  "DisplayName","Alias","PrimarySmtpAddress","ManagedBy"
```

### Local development

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export UPLOAD_DIR=./uploads REPORTS_DIR=./generated_reports LOG_DIR=./logs DB_PATH=./data/pivot.db
uvicorn app.main:app --reload --port 8000
```

### Tests

```bash
cd backend
pip install pytest httpx
python -m pytest -q
```

## Configuration

Environment variables (set in `docker-compose.yml`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `UPLOAD_DIR` | `/app/uploads` | Uploaded files |
| `REPORTS_DIR` | `/app/generated_reports` | Email attachments and previews |
| `LOG_DIR` | `/app/logs` | Rotating log files |
| `DB_PATH` | `/app/data/pivot.db` | SQLite database |
| `USERS_CSV_PATH` | `/app/Users.csv` | User directory |
| `DISTRIBUTION_LISTS_CSV_PATH` | `/app/DistributionLists.csv` | Distribution lists |
| `APP_AUTH_USERNAME` / `APP_AUTH_PASSWORD` | unset | When both are set, every page and API (except `/health`) requires HTTP Basic login |
| `CORS_ALLOW_ORIGINS` | unset | Comma-separated origins allowed to call the API cross-origin |

Runtime settings (app name, timezone, max upload size up to 500 MB) are on
the **Settings** page; SMTP is configured on **SMTP Settings**. Limits:
100,000 rows and 200 columns per sheet, 10,000 pivot result rows.

## Pages

| Path | Page |
| --- | --- |
| `/` | Upload |
| `/datasets`, `/preview/{id}`, `/manage` | Datasets, preview, column types |
| `/pivot` | Pivot Builder |
| `/email/settings`, `/email/history` | SMTP settings, sent history |
| `/settings`, `/diagnostics`, `/logs` | Admin |
| `/admin/audit`, `/admin/cleanup` | Delete audit, cleanup utility |

## API

| Method & path | Purpose |
| --- | --- |
| `POST /api/upload` | Upload and parse a file |
| `GET /api/datasets`, `GET /api/dataset/{id}`, `DELETE /api/dataset/{id}` | List, detail, delete |
| `GET /api/dataset/{id}/sheet/{sheet}/columns` · `/preview` · `/field/{field}/values` | Sheet metadata, preview rows, distinct filter values |
| `POST /api/pivot` | Compute a pivot |
| `POST /api/pivot/validate` | Validate a configuration without computing |
| `POST /api/pivot/drilldown` | Source records behind one pivot row |
| `POST /api/pivot/delete-records` | Soft-delete records behind pivot rows (`dryRun: true` to count only) |
| `POST /api/email/preview`, `POST /api/email/send` | Build / send a report email |
| `GET/POST /api/email/smtp-settings`, `POST /api/email/test` | SMTP configuration |
| `GET /api/email/history`, `GET /api/email/history/{id}/attachment` | Sent history |
| `GET /api/users/suggest`, `GET /api/users/status`, `POST /api/users/reload` | Recipient directory |
| `GET/POST /api/settings` | Application settings |
| `GET /api/logs`, `GET /api/admin/audit`, `/api/admin/cleanup/*`, `GET /api/diagnostics`, `GET /health` | Admin |

The pivot request shape is documented in [`PIVOT_CONTRACT.md`](./PIVOT_CONTRACT.md).

## Project structure

```text
backend/app/
  main.py               app, middleware (auth, cache headers), error pages
  templating.py         shared Jinja templates + app_name()/app_version
  config/ models/ repositories/ schemas/
  routes/               page + API routes
  services/
    pivot_service.py        pivot engine, selections, sheet loading/cache
    soft_delete_service.py  Delete Records + audit
    email_service.py        email body + send orchestration
    attachment_service.py   .xlsx attachment
    user_directory.py       Users.csv / DistributionLists.csv cache
  static/js/            pivot.js (controller), pivot-grid.js, drilldown-*,
                        email-manager.js, ui.js (toasts/confirm/fetch), …
  static/css/styles.css design tokens (light/dark) + component styles
  templates/            base.html (app shell) + one template per page
backend/tests/          pytest suite
nginx/nginx.conf        reverse proxy (client_max_body_size 510M)
```

## Important implementation notes

- **Selections must identify a row exactly.** Every pivot row carries
  `__rowFields` (its row-field values, in both layouts); drill-down, email
  and delete use it. An empty selection matches nothing and an unknown field
  is an error — never widen a match silently.
- **Act on the rendered pivot.** The frontend sends the configuration that
  produced the visible result (`appState.lastPayload`), not the live form.
- **Soft delete** stores a hash per record (`row_keys.frame_row_keys`); the
  writer and the reader must use the same function or deleted rows reappear.
- **Totals** (subtotals, row/column/grand totals) are aggregated from the
  source records, never from already-aggregated cells.
- After changing a JS file, bump its `?v=` query string in the template so
  browsers fetch the new version.
