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
  layout, grand / row / column totals and subtotals, **Top / Bottom N** and
  value thresholds (e.g. "only categories with more than 100 alerts").
- **Saved pivots** — save a configuration by name and reopen it in one
  click (`/pivot?saved=<id>`).
- **Result grid** (AG Grid) — search, expand / collapse groups, freeze /
  hide columns, number / date / conditional formatting, copy, print,
  Excel export.
- **Drill-down** into the source records of one or more pivot rows.
- **Email** selected pivot rows via SMTP with an `.xlsx` attachment of the
  matching records; recipient typeahead from `Users.csv` /
  `DistributionLists.csv`; reusable **email templates** with placeholders
  (`{date}`, `{datetime}`, `{dataset}`, `{sheet}`, `{rows}`); sent history
  with re-download.
- **Scheduled reports** — email a saved pivot daily, on weekdays, weekly or
  monthly at a set time (app timezone), with "send now" and run status.
- **Delete Records** — soft-deletes the records behind selected rows (the
  uploaded file is never modified), with a dry-run count, an audit log and
  **Restore** to undo a delete.
- **Refresh data** — replace a dataset's file with a new export while
  keeping its saved pivots, schedules and deleted records.
- **Admin** — settings (app name, timezone, upload limit), diagnostics,
  log viewer, delete audit, cleanup utility, `/health`.
- Light / dark / system theme; responsive layout.

## Tech stack

FastAPI (Python 3.11) · pandas + openpyxl · SQLite (SQLAlchemy + Alembic) · Jinja2 +
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
| `APP_SECRET_KEY` | unset | Key for encrypting the SMTP password. Unset = a key file `secret.key` is created next to the database |
| `SCHEDULER_ENABLED` | `1` | Set `0` to stop this process from sending scheduled reports |

Runtime settings (app name, timezone, max upload size up to 500 MB) are on
the **Settings** page; SMTP is configured on **SMTP Settings** (username and
password are optional for relays that need no login). Limits: 100,000 rows
and 200 columns per sheet, 10,000 pivot result rows.

**Secrets:** the SMTP password is stored encrypted (Fernet). Back up
`secret.key` together with `pivot.db` (both are on the `db_data` volume),
or set `APP_SECRET_KEY`; without the key the password must be re-entered.

### Database migrations

The schema is managed with Alembic (`backend/migrations/`) and upgraded
automatically on startup; databases from before migrations existed are
detected and upgraded in place. To add a migration after changing a model:

```bash
cd backend
alembic revision --autogenerate -m "describe the change"
```

## Pages

| Path | Page |
| --- | --- |
| `/` | Upload |
| `/datasets`, `/preview/{id}`, `/manage` | Datasets, preview, column types |
| `/pivot` | Pivot Builder |
| `/reports` | Scheduled reports + saved pivots |
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
| `POST /api/admin/audit/{id}/restore` | Undo a delete |
| `POST /api/dataset/{id}/refresh` | Replace a dataset's file (multipart `file`) |
| `GET/POST /api/saved-pivots`, `GET/PUT/DELETE /api/saved-pivots/{id}` | Saved pivots |
| `GET/POST /api/schedules`, `GET/PUT/DELETE /api/schedules/{id}`, `POST /api/schedules/{id}/run` | Scheduled reports |
| `GET/POST /api/email/templates`, `PUT/DELETE /api/email/templates/{id}` | Email templates |
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
    soft_delete_service.py  Delete Records, audit, restore
    saved_pivot_service.py  saved pivots
    scheduler_service.py    scheduled reports (next-run maths + background loop)
    email_template_service.py
    email_service.py        email body + send orchestration
    attachment_service.py   .xlsx attachment
    user_directory.py       Users.csv / DistributionLists.csv cache
  static/js/            pivot.js (controller), pivot-grid.js, drilldown-*,
                        email-manager.js, ui.js (toasts/confirm/fetch), …
  static/css/styles.css design tokens (light/dark) + component styles
  templates/            base.html (app shell) + one template per page
backend/migrations/     Alembic migrations (run on startup)
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
- **Value filters** (Top N / thresholds) remove whole row groups from the
  records before aggregation, so subtotals and grand totals match the rows
  shown; a group's value is its total across all column groups.
- **Scheduler**: one background thread per app process polls every 30 s;
  each due run is claimed with a conditional UPDATE so it is sent once even
  with several processes. Runs missed by more than 12 h are skipped.
- After changing a JS file, bump its `?v=` query string in the template so
  browsers fetch the new version.
