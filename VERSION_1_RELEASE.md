# Pivot App — Version 1.0 Release

**Excel Pivot Analysis + Stakeholder Mailing Platform**

Pivot App is an internal operational web app for uploading Excel/CSV datasets,
extracting reusable metadata, configuring pivots in the browser, computing
pivots on the backend, drilling down into raw records, deleting records
softly, sending reports by email, and recovering from browser crashes.

This document is the **V1 reference** — it summarises the feature set,
architecture, deployment steps, and known limitations that should be reviewed
before releasing Pivot App into general internal use.

---

## 1. Features

The application ships with everything from Phases 1 – 8. For a detailed
walkthrough of each phase, see the per-section headings in the README. The
high-level feature map:

| Area | Features |
| --- | --- |
| **Upload** | `.xlsx` + `.csv` up to 50 MB (runtime-configurable), three-layer validation (extension, MIME, magic bytes), per-sheet column-type inference, first-N-row preview, friendly validation errors. |
| **Datasets** | `/manage` browser with sheet + column metadata, AG Grid preview, delete flow with soft-delete cascade. |
| **Pivot** | Rows / Columns / Values / Filters / Date Grouping / Sorting / Totals, validation endpoint (no file I/O), compute endpoint, support for `count` / `sum` / `average` / `min` / `max`, layout (compact / tabular). |
| **Result UI** | AG Grid with sort / filter / resize / hide, grand totals pinned to the bottom, row totals pinned to the right, pivot statistics panel, selection bar, fullscreen overlay, hidden config panel. |
| **Drill-down** | Double-click or multi-select drill-down into raw records; AG Grid modal with search, sort, column visibility, dedup, summary + criteria cards, .xlsx export. |
| **Email** | Composer modal with To/CC/BCC + recent-recipient typeahead + HTML preview + .xlsx attachment (merged + deduped), SMTP settings page, email history page with re-download. |
| **Excel-like** | Expand/collapse row groups, Repeat Item Labels (Tabular Form), real subtotal rows, per-column totals, conditional formatting, number/date formats, freeze/hide columns, auto-fit, copy (TSV), print view. |
| **Soft delete** | "Delete Records" button on the Pivot page soft-deletes the raw records behind the selected pivot rows; automatic pivot refresh; full audit trail; records are excluded from pivot, drill-down, exports, and email attachments. |
| **Settings** | Application name, company name, timezone, max upload size, default export folder — stored in SQLite, applied at runtime. |
| **Health** | `GET /health` for Docker health checks, application status, database status, folder status, SMTP status, version, current time. |
| **Logging** | Rotating log file under `LOG_DIR`, mirrored to SQLite, searchable Log Viewer page (search / date / level / category filters), download. |
| **Diagnostics** | `/diagnostics` page + `/api/diagnostics` JSON: application version, Python/SQLite versions, OS, disk space, dataset count, storage usage, health status. |
| **Cleanup** | Admin Cleanup utility for temp exports, old logs, orphaned uploads, old cached files — preview + confirmation + per-category file counts + disk-space-to-recover. |
| **Error pages** | Friendly 400/403/404/500 pages with friendly message, "Return Home" and "Return Previous Page" buttons, application branding, no stack traces. |
| **Caching** | In-memory cache for dataset metadata, sheet columns, recent pivot results, drill-down datasets; auto-invalidated on dataset changes. |
| **Draft recovery** | Pivot configuration auto-saved to `localStorage`; on reload, a "Restore previous session" banner lets the user restore or discard. |
| **Loading UX** | Full-card loading overlay during upload, button spinners during validation / compute / drill-down / export / email preview / send / delete; double-click guard on every action button. |
| **Theme** | Three-mode (System / Light / Dark) theme with pre-paint inline script (no FOUC), AG Grid dual-theme swap, OS theme detection. |

---

## 2. Architecture

The application keeps the same architecture as Phases 1 – 7 — the Phase 8
additions are entirely **additive** and live alongside the existing layers
without disturbing the request/response contracts or the existing routes.

```
              ┌──────────────────────────────────────────────┐
              │                   Browser                    │
              │  Vanilla JS + Bootstrap 5.3 + AG Grid 31      │
              │  pivot.js (controller) + 12 sibling modules    │
              └──────────────────┬───────────────────────────┘
                                 │ JSON over fetch()
              ┌──────────────────▼───────────────────────────┐
              │               FastAPI (sync)                  │
              │  Routes → Services → Repositories → SQLAlchemy │
              │  ────────────────────────────────────────     │
              │  Phase 8 modules (all additive):              │
              │   • app_settings, app_log, soft_deleted_record│
              │   • delete_audit, deleted_dataset             │
              │   • settings_service, soft_delete_service,    │
              │     cleanup_service, metadata_cache           │
              │   • app_logging (rotating file + DB mirror)  │
              │   • file_validation (extension/MIME/magic)   │
              └──────────────────┬───────────────────────────┘
                                 │
              ┌──────────────────▼───────────────────────────┐
              │ SQLite (single file) + filesystem             │
              │  /app/data/pivot.db   — datasets, sheets,     │
              │                             columns, settings, │
              │                             logs, audit, soft │
              │                             deletes           │
              │  /app/uploads           — original files      │
              │  /app/generated_reports — email attachments   │
              │  /app/logs              — rotating log files  │
              └──────────────────────────────────────────────┘
```

### Architectural invariants (preserved from Phases 1 – 7)

- **No React / Vue / Angular / Webpack / Vite.** Vanilla JS + Jinja2 SSR only.
- **Modular backend** — `routes / services / repositories / utils` separation.
  Business logic stays out of route files (only the route signature, the
  call into the service, and the response shaping live in routes).
- **CamelCase JSON on the wire**, `populate_by_name=True` Pydantic models so
  snake_case callers still work.
- **One pivot request/response contract** — Phase 7 + Phase 8 add
  `displayOptions`, `totals.repeatItemLabels`, and the soft-delete endpoint
  without changing the existing `POST /api/pivot` shape.

---

## 3. Folder Structure (post-Phase 8)

```
pivot-app/
├── backend/
│   ├── app/
│   │   ├── main.py                        # FastAPI factory, routers, error handlers
│   │   ├── config/
│   │   │   ├── database.py                # SQLAlchemy engine + Base + get_db()
│   │   │   └── settings.py                # env-driven paths + limits
│   │   ├── models/                        # SQLAlchemy ORM (one file per table)
│   │   │   ├── dataset.py                 #   datasets
│   │   │   ├── sheet.py                   #   dataset_sheets
│   │   │   ├── column.py                  #   dataset_columns
│   │   │   ├── smtp_settings.py           #   smtp_settings  (Phase 6)
│   │   │   ├── email_history.py           #   email_history  (Phase 6)
│   │   │   ├── recent_recipient.py        #   recent_recipients (Phase 6)
│   │   │   ├── app_settings.py            #   app_settings  (Phase 8)
│   │   │   ├── app_log.py                 #   app_log       (Phase 8)
│   │   │   ├── soft_deleted_record.py     #   soft_deleted_records (Phase 8)
│   │   │   ├── delete_audit.py            #   delete_audit  (Phase 8)
│   │   │   └── deleted_dataset.py         #   deleted_datasets  (Phase 8)
│   │   ├── repositories/                  # DB CRUD (one per model)
│   │   │   ├── dataset_repository.py
│   │   │   ├── sheet_repository.py
│   │   │   ├── column_repository.py
│   │   │   ├── smtp_settings_repository.py
│   │   │   ├── email_history_repository.py
│   │   │   └── app_settings_repository.py
│   │   ├── routes/                        # HTTP boundary
│   │   │   ├── upload_routes.py           #   /, /datasets, /preview, /api/upload
│   │   │   ├── dataset_routes.py          #   /manage, /api/dataset/*
│   │   │   ├── pivot_routes.py            #   /pivot, /api/pivot/* (incl. delete-records)
│   │   │   ├── email_routes.py            #   /email/*, /api/email/*
│   │   │   ├── settings_routes.py         #   /settings, /api/settings         (Phase 8)
│   │   │   ├── health_routes.py           #   /health, /diagnostics, /api/diagnostics
│   │   │   ├── log_routes.py              #   /logs, /api/logs/*                (Phase 8)
│   │   │   └── admin_routes.py            #   /admin/cleanup, /admin/audit, /api/admin/* (Phase 8)
│   │   ├── schemas/                       # Pydantic request/response models
│   │   │   ├── dataset.py
│   │   │   ├── pivot.py                   # Phase 7 + 8 contract
│   │   │   ├── email.py
│   │   │   └── settings.py                # Phase 8
│   │   ├── services/                      # Business logic
│   │   │   ├── excel_service.py
│   │   │   ├── dataset_service.py
│   │   │   ├── pivot_service.py           # Phase 7 engine
│   │   │   ├── pivot_validation_service.py
│   │   │   ├── attachment_service.py      # Phase 6
│   │   │   ├── smtp_service.py            # Phase 6
│   │   │   ├── email_service.py           # Phase 6
│   │   │   ├── email_history_service.py   # Phase 6
│   │   │   ├── app_settings_service.py    # Phase 8
│   │   │   ├── app_logging.py             # Phase 8 (rotating file + DB mirror)
│   │   │   ├── soft_delete_service.py     # Phase 8
│   │   │   ├── cleanup_service.py         # Phase 8
│   │   │   └── metadata_cache.py          # Phase 8 (in-process cache)
│   │   ├── static/
│   │   │   ├── css/styles.css
│   │   │   └── js/                        # 13 modules (Pivot + Drilldown + Email + Phase 8)
│   │   │       ├── theme.js
│   │   │       ├── upload.js
│   │   │       ├── manage.js
│   │   │       ├── pivot.js               # controller (~1700 lines, Phase 8 wiring)
│   │   │       ├── pivot-grid.js
│   │   │       ├── pivot-display.js
│   │   │       ├── pivot-export.js
│   │   │       ├── drilldown-selection.js
│   │   │       ├── drilldown-manager.js
│   │   │       ├── drilldown-export.js
│   │   │       ├── email-manager.js       # Phase 8 double-click guard
│   │   │       ├── preview-manager.js
│   │   │       ├── smtp-settings.js
│   │   │       ├── email-history.js
│   │   │       ├── settings.js            # Phase 8
│   │   │       ├── diagnostics.js         # Phase 8
│   │   │       ├── logs.js                # Phase 8
│   │   │       ├── cleanup.js             # Phase 8
│   │   │       └── audit.js               # Phase 8
│   │   ├── templates/
│   │   │   ├── base.html                  # navbar + theme bootstrap
│   │   │   ├── upload.html                # Phase 8 — max-size display + overlay
│   │   │   ├── datasets.html
│   │   │   ├── preview.html
│   │   │   ├── manage.html
│   │   │   ├── pivot.html                 # Phase 8 — Delete Records + draft banner + modal
│   │   │   ├── email_settings.html
│   │   │   ├── email_history.html
│   │   │   ├── settings.html              # Phase 8
│   │   │   ├── diagnostics.html           # Phase 8
│   │   │   ├── logs.html                  # Phase 8
│   │   │   ├── cleanup.html               # Phase 8
│   │   │   ├── audit.html                 # Phase 8
│   │   │   └── error.html                 # Phase 8 — friendly 400/403/404/500
│   │   └── utils/
│   │       ├── file_utils.py
│   │       └── file_validation.py         # Phase 8 — ext/MIME/magic/full
│   ├── uploads/                           # datasets
│   ├── generated_reports/                 # email attachments
│   │   ├── email_previews/
│   │   └── email_attachments/
│   ├── logs/                              # Phase 8 — rotating log files
│   ├── data/                              # SQLite file
│   ├── requirements.txt
│   └── Dockerfile
├── nginx/
│   └── nginx.conf
├── docker-compose.yml
├── build_start.sh
├── PIVOT_CONTRACT.md
├── Phase1 … Phase7, Phase8                # per-phase spec files
├── README.md
└── VERSION_1_RELEASE.md                   # ← this file
```

---

## 4. API Endpoints

The full list of HTTP endpoints exposed by the application. All endpoints
are **additive** over the Phases 1 – 7 surface; no existing endpoint has
been changed.

### Page routes

| Method | Path                | Phase | Purpose                              |
| ------ | ------------------- | ----- | ------------------------------------ |
| GET    | `/`                 | 1     | Upload page                          |
| GET    | `/datasets`         | 1     | List uploaded datasets               |
| GET    | `/preview/{id}`     | 1     | Dataset preview page                 |
| GET    | `/manage`           | 2     | Dataset management UI                |
| GET    | `/pivot`            | 3     | Pivot builder UI                     |
| GET    | `/email/settings`   | 6     | SMTP configuration page              |
| GET    | `/email/history`    | 6     | Email history page                   |
| GET    | `/settings`         | **8** | Application settings page            |
| GET    | `/diagnostics`      | **8** | Diagnostics page                     |
| GET    | `/logs`             | **8** | Log Viewer page                      |
| GET    | `/admin/cleanup`    | **8** | Cleanup utility page                 |
| GET    | `/admin/audit`      | **8** | Delete audit page                    |
| GET    | `/docs`             | —     | Swagger API docs (FastAPI built-in)  |
| GET    | `/redoc`            | —     | ReDoc API docs (FastAPI built-in)    |

### Phase 1 – 7 API endpoints (unchanged)

See the README for the full list. The Phase 7 endpoint shape is:

- `POST /api/pivot/validate` — pure metadata validation
- `POST /api/pivot` — compute pivot
- `POST /api/pivot/drilldown` — drill-down

### Phase 8 API endpoints (new)

| Method | Path                                            | Purpose                                        |
| ------ | ----------------------------------------------- | ---------------------------------------------- |
| GET    | `/api/settings`                                 | Get current application settings              |
| POST   | `/api/settings`                                 | Save current application settings             |
| GET    | `/health`                                       | Health check (Docker + status pages)          |
| GET    | `/api/diagnostics`                              | JSON diagnostics (version, OS, disk, ...)     |
| GET    | `/api/logs?q=&level=&category=&date_from=&date_to=&limit=` | Search/filter log records          |
| GET    | `/api/logs/download`                            | Download the current `pivot_app.log` file      |
| GET    | `/api/admin/cleanup/preview?older_than_days=N`  | Preview cleanup targets                        |
| POST   | `/api/admin/cleanup/run`                        | Run cleanup                                    |
| GET    | `/api/admin/audit?q=&status=&dataset_id=&limit=`| List delete audit rows                        |
| POST   | `/api/pivot/delete-records`                     | Soft-delete raw records behind pivot rows     |

### `POST /api/pivot/delete-records`

```jsonc
// Request
{
  "pivotRequest": { /* same shape as POST /api/pivot */ },
  "selections": [
    { "Region": "North", "Category": "Payments" },
    { "Region": "South", "Category": "Refunds" }
  ]
}

// Response 200
{
  "auditId":   42,
  "matched":   158,        // matched across all selections (additive)
  "deleted":   143,        // post-dedup count actually inserted
  "selections": 2
}
```

Errors: `400 Bad Request` (empty selections / no dataset), `500` (unexpected).

### `GET /health` response

```json
{
  "status":      "ok",                            // ok | degraded | down
  "version":     "1.0.0",
  "currentTime": "2026-07-07T08:00:00.000Z",
  "database":    { "ok": true, "datasetCount": 12, "sizeMb": 2.4, ... },
  "uploadsFolder": { "exists": true, "writable": true, "freeGb": 19.8, ... },
  "reportsFolder": { ... },
  "logsFolder":    { ... },
  "smtp":          { "configured": true, "host": "smtp.gmail.com", ... }
}
```

---

## 5. Database Schema (post-Phase 8)

Eight tables, all created on first startup via `init_db()`. Phase 8 added
**five** new tables; the existing Phase 1 – 6 tables are unchanged.

| Table                  | Phase | Notes |
| ---------------------- | ----- | ----- |
| `datasets`             | 1     | Original upload metadata |
| `dataset_sheets`       | 1     | One row per sheet |
| `dataset_columns`      | 1     | Inferred column type per sheet |
| `smtp_settings`        | 6     | Singleton row, password in plain text (V1) |
| `email_history`        | 6     | One row per send attempt |
| `recent_recipients`    | 6     | Unique on `(address, recipient_type)` |
| `app_settings`         | **8** | Singleton row, holds app name / company / timezone / max upload size / default export dir |
| `app_log`              | **8** | Mirror of rotating log file; trimmed to 5 000 rows |
| `soft_deleted_records` | **8** | Per-dataset / per-sheet soft-delete list; source-key is a SHA-256 of the row JSON |
| `delete_audit`         | **8** | One row per pivot-row delete operation; status / count / selection criteria |
| `deleted_datasets`     | **8** | Snapshot of dataset rows at delete time (admin breadcrumb) |

### Cascade rules

- Deleting a `datasets` row cascades to `dataset_sheets`, `dataset_columns`,
  `soft_deleted_records`, and `delete_audit` for that dataset
  (the cascading is performed explicitly by the dataset delete route).
- Deleting a single `soft_deleted_records` row does NOT cascade (the audit row
  is kept as a historical breadcrumb).
- The `email_history` table is **never** affected by dataset deletes — the
  history is independent of the dataset lifecycle.

---

## 6. Caching Strategy

A single in-process cache (`app.services.metadata_cache`) provides:

| Slot              | Key                              | Value                          | TTL |
| ----------------- | -------------------------------- | ------------------------------ | --- |
| `dataset_meta`    | `dataset_id`                     | dataset detail (with sheets/columns) | 5 min |
| `column_meta`     | `(dataset_id, sheet_name)`       | column list for a sheet         | 5 min |
| `pivot_result`    | `(dataset_id, sheet_name, h)`    | full PivotResponse              | 5 min |
| `drilldown_data`  | `(dataset_id, sheet_name)`       | in-memory DataFrame              | 5 min |

- The cache is process-local (not shared across gunicorn workers).
- **Invalidation** is triggered automatically by:
  - `POST /api/upload` (new dataset) — invalidates the affected dataset.
  - `POST /api/pivot/delete-records` (soft delete) — invalidates the dataset
    so the next pivot re-computes against the un-deleted data.
  - `DELETE /api/dataset/{id}` — invalidates the dataset (and removes the
    on-disk file + soft-delete rows for the dataset).
  - `POST /api/admin/cleanup/run` (cleanup) — invalidates the dataset so
    any in-memory drilldown DataFrame is rebuilt from the new file state.

---

## 7. Soft Delete — Implementation Details

Soft delete is the **delete strategy** for the new "Delete Records" feature
on the Pivot page. The user selects one or more pivot rows, clicks **Delete
Records**, and the raw records behind those rows are removed from every
subsequent view (pivot, drill-down, exports, email attachments).

### How it works

1. The frontend (`pivot.js`) builds a list of `{field: value}` selections
   from the currently selected pivot rows (using `DrilldownSelection` so
   the selection shape is identical to drill-down and email).
2. The frontend POSTs to `/api/pivot/delete-records` with the same
   `pivotRequest` the user used to compute the pivot (so the engine can
   rebuild the exact filter / aggregation context) plus the list of
   `selections`.
3. The backend (`soft_delete_service.soft_delete_from_pivot`) calls
   `build_drilldown` **once per selection**, merges the resulting records
   with a stable SHA-256 dedup key, and inserts a `soft_deleted_records`
   row for each unique record.
4. A single `delete_audit` row captures the operation: dataset id, sheet
   name, pivot row count, matched count, deleted count, selection criteria
   (JSON), and `status` (`success` / `failed`).
5. The in-memory cache is invalidated for the dataset so the next pivot
   re-computes fresh.
6. The frontend re-issues the pivot compute automatically — the user sees
   the updated numbers without a manual refresh.

### Why soft delete, not hard delete

- The source file (`.xlsx`) is a binary blob; mutating it in place is
  not practical at this scale.
- Soft delete survives re-uploads of the same file — the same
  `source_key` is re-derived and the same rows stay out.
- The audit table records every operation, so a future hard-delete pass
  (from the Cleanup utility) can be reviewed first.
- No regression to existing user workflow — the pivot page, drill-down
  modal, exports, and email attachments all work exactly as before; the
  deleted records simply do not appear in any of them.

### Recovery

- A soft-deleted record can be recovered by removing the corresponding
  `soft_deleted_records` row (e.g. via the SQLite CLI or a future admin UI).
- The audit table keeps the selection criteria, so an admin can re-run
  the soft delete for a different machine or verify what was removed.

---

## 8. Logging Architecture

Three layers, designed to fail safely:

1. **Console** — every INFO+ record is written to stderr (visible in the
   `docker compose logs` output).
2. **Rotating file handler** — under `LOG_DIR/pivot_app.log` (5 MB × 5
   backups ≈ 25 MB max). Survives container restarts when mounted as a
   volume.
3. **SQLite mirror** — the `app_log` table holds the most recent 5 000
   records for fast search on the Log Viewer page. The mirror is
   best-effort: a logging failure is swallowed so it never breaks a
   request.

Every domain event uses a stable `category` so the Log Viewer can filter:

- `startup` / `shutdown` — application lifecycle
- `upload` — file upload accepted / rejected
- `dataset` — dataset created / deleted
- `pivot` — pivot computed
- `pivot_delete` — soft delete started / completed / failed (always
  searchable from the audit page)
- `drilldown` — drill-down opened
- `export` — Excel export produced
- `email_preview` / `email_sent` / `email_failed` — email lifecycle
- `cleanup` — cleanup utility executed
- `error` — unhandled exceptions (also surfaces on the global error page)
- `auth` — placeholder for future authentication events

The helper `app.services.app_logging.log_event()` is the single entry
point for application code — pass a level, a message, an optional
category, and optional details. Never use `print()` or call the logger
directly from application code.

---

## 9. Diagnostics Architecture

`/api/diagnostics` returns a snapshot of every important subsystem:

```jsonc
{
  "application": { "version": "1.0.0", "python": "3.11.x", "sqlite": "3.x", "os": "...", "hostname": "..." },
  "health":      { "status": "ok", "checkedAt": "..." },
  "database":    { "ok": true, "datasetCount": 12, "sizeMb": 2.4, ... },
  "folders":     { "uploads": { "exists", "writable", "freeGb", "totalGb" }, "reports": { ... }, "logs": { ... } },
  "smtp":        { "configured": true, "host": "...", "username": "...", "sender": "..." },
  "storage":     { "datasetCount": 12, "uploadsMb": 18.4, "reportsMb": 0.2 }
}
```

The `/diagnostics` page renders the same data in Bootstrap cards so an
admin can read it at a glance. Both endpoints are read-only and safe to
poll.

---

## 10. Cleanup Strategy

The `/admin/cleanup` page exposes five independent cleanup buckets:

| Bucket             | What it deletes                                            | Default age |
| ------------------ | ---------------------------------------------------------- | ----------- |
| `temp_exports`     | One-shot email preview attachments                          | 7 days      |
| `drilldown_files`  | Alias of `temp_exports` (Phase 5 backwards compatibility) | 7 days      |
| `old_uploads`      | Orphaned uploaded files (no matching `datasets` row)       | n/a         |
| `old_logs`         | Rotated log backups (keeps the current `pivot_app.log`)    | 7 days      |
| `cached_files`     | Placeholder for future caches (no-op today)                | n/a         |

The flow:

1. `/api/admin/cleanup/preview` returns a list of `{key, fileCount,
   totalBytes}` for each bucket.
2. The admin ticks the buckets they want to clean and clicks **Clean now**.
3. The browser shows a confirmation modal with the per-bucket summary
   (file count + MB) so the admin sees the impact before clicking
   "Yes, clean now".
4. `/api/admin/cleanup/run` returns `{deleted: {key: {filesDeleted,
   bytesFreed}}, freedBytes, freedMb}` and the UI shows a success toast.
5. Every cleanup operation is logged under `category="cleanup"`.

The page is intended for internal IT / data engineering use. It does
**not** touch datasets with active metadata, only files that are clearly
orphaned or past the configured age.

---

## 11. Health Endpoint

`GET /health` is the single endpoint intended for Docker health checks
and external monitoring. Recommended Docker compose snippet:

```yaml
services:
  pivot:
    build: ./backend
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
```

The endpoint returns:

- `200 OK` when `status == "ok" | "degraded"`
- `503 Service Unavailable` when `status == "down"`

Top-level status logic:

- `ok` — DB is reachable + uploads folder is writable.
- `degraded` — DB is reachable but the uploads or reports folder is missing
  / read-only. The app can still serve pivot queries against cached data.
- `down` — DB is unreachable. The app cannot serve any request.

---

## 12. Error Pages

Four friendly templates (`error.html`), each showing:

- The HTTP status code in a large, muted style.
- A friendly heading (e.g. "Page not found").
- A user-readable message (no stack trace).
- Two buttons: **Return Home** and **Return Previous Page** (the second
  uses `history.back()` if available, otherwise falls back to Home).
- The application name as a footer.

The templates are wired into the FastAPI exception handlers in `main.py`
for status codes `400`, `403`, `404`, and `500`. **Stack traces are
NEVER rendered** to the browser — they are written to the log file with
`logger.exception(...)` so an admin can read them via the Log Viewer.

---

## 13. Docker Deployment

### Production compose

```yaml
services:
  pivot:
    build: ./backend
    container_name: pivot-app
    restart: unless-stopped
    ports:
      - "5000:8000"        # Nginx → FastAPI
    volumes:
      - ./backend/uploads:/app/uploads
      - ./backend/generated_reports:/app/generated_reports
      - ./backend/logs:/app/logs
      - ./backend/data:/app/data
    environment:
      - DB_PATH=/app/data/pivot.db
      - UPLOAD_DIR=/app/uploads
      - REPORTS_DIR=/app/generated_reports
      - LOG_DIR=/app/logs
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s

  nginx:
    image: nginx:1.27-alpine
    container_name: pivot-nginx
    depends_on:
      pivot:
        condition: service_healthy
    ports:
      - "5000:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
```

### One-shot start

```bash
git clone <repo> pivot-app
cd pivot-app
./build_start.sh              # builds + starts in detached mode
# OR
docker compose up --build
```

The app is served by Nginx at `http://localhost:5000`.

### Local development (no Docker)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
DB_PATH=./data/pivot.db \
  UPLOAD_DIR=./uploads \
  REPORTS_DIR=./generated_reports \
  LOG_DIR=./logs \
  uvicorn app.main:app --reload --port 8000
```

Local URL: `http://localhost:8000`.

---

## 14. Manual Test Checklist (V1)

The 20-test Phase 8 acceptance suite from the spec — every test passes
end-to-end against the deployed build.

1. **Open Settings** — `/settings` → change application name + max upload
   size, click Save → reload, the new value is persisted.
2. **Call /health** — returns a JSON with `status` + `version` + folder
   statuses + DB status.
3. **Upload an invalid file** — binary content renamed to `.csv` → rejected
   with a friendly message; no half-uploaded file left on disk.
4. **Upload an oversized file** — rejected with a friendly "maximum allowed
   is N MB" message; the configured max size is honoured.
5. **Generate a pivot** — the full-card loading overlay is visible while
   the request is in flight; the Generate button is disabled; on success
   the overlay disappears and the grid renders.
6. **Send an email** — the Send button shows a spinner and is disabled
   while the SMTP request is in flight; a second click is ignored.
7. **Delete records from one pivot row** — confirmation modal shows the
   count + criteria + dataset + sheet + warning; on confirm, the soft
   delete completes and the audit row is created.
8. **Delete records from multiple pivot rows** — the same flow works;
   multi-selection results in a single audit row with `selections > 1`.
9. **Verify automatic pivot refresh** — after delete, the pivot
   re-computes and the updated numbers appear without a manual click.
10. **Verify drill-down after deletion** — opening a drill-down on any
    other pivot row excludes the deleted records.
11. **Verify exports after deletion** — the .xlsx export from the pivot
    page (via `pivot-export.js`) excludes the deleted records.
12. **Verify email attachment after deletion** — clicking Preview on the
    email composer shows the post-delete attachment record count.
13. **Restart the browser while composing an email** — on the next page
    open the draft recovery banner appears; clicking Restore brings the
    form back; clicking Discard clears it.
14. **Run Cleanup Utility** — preview lists the temp exports + logs +
    orphans; selecting a category and clicking "Clean now" runs the
    operation and shows the freed MB.
15. **Open Diagnostics** — every section (Application, Database, Folders,
    Storage, SMTP) renders with current data.
16. **Review Log Viewer** — search, level filter, category filter, date
    filter all work; Download Log File returns `pivot_app.log`.
17. **Trigger a 404 page** — visit `/this-does-not-exist` → friendly 404
    page with Return Home + Return Previous Page buttons.
18. **Review application performance** — re-render a pivot after a
    small configuration change; the in-memory cache returns the same
    result without re-loading the file.
19. **Review code quality** — every new module follows the existing
    layered structure (routes / services / repositories / utils); the
    routes are thin; the services are pure-ish and testable; no new
    dependencies were added.
20. **Final acceptance test** — upload Excel → configure Pivot →
    Generate → Drill-down → Select rows → Preview Email → Send → Delete
    Records → Pivot auto-refreshes → Export → Logs visible → /health
    passes → Draft Recovery works.

---

## 15. Known Limitations / V2 Roadmap

These are **intentionally out of scope** for V1 (per the spec). The
schemata and code paths are already designed to accommodate them with
minimal refactoring.

- **Authentication / Authorisation** — V1 is single-tenant and assumes
  the application is reachable only by trusted users (e.g. behind a
  VPN). The V2 addition would be a session cookie + role check in the
  FastAPI dependency layer; the `recent_recipients` and `delete_audit`
  tables already have a `user` placeholder.
- **SMTP password encryption** — the password is currently stored in
  plaintext in `smtp_settings.password`. A `cryptography.fernet` wrapper
  can be added behind a one-line change in `smtp_settings_repository`.
- **Scheduled / recurring emails** — `email_history.pivot_payload_json`
  already captures the full request, so a future scheduler can re-render
  and re-send without re-querying the dataset. The cron-style trigger is
  the missing piece.
- **Recipient rules / saved templates** — both can be added as new
  tables without breaking the existing `EmailSendRequest` shape.
- **Multi-user concurrency** — the application is safe to use from
  multiple browsers against a single FastAPI worker (the in-memory
  cache is per-process, and the SQLite writes are serialised). Scaling
  to multiple gunicorn workers is straightforward but the cache will
  become per-worker; a future V2 could swap `metadata_cache` for
  Redis.
- **Display options persistence** — number / date / conditional formats
  are applied per-pivot-render today. Persisting them per-user (or
  per-dataset) would be a useful follow-up.
- **Hard-delete** — the soft delete strategy is the default; the
  Cleanup utility could grow a "permanent delete" option that removes
  the `soft_deleted_records` row + rewrites the source file in place.
- **Push notifications / dashboards** — explicitly out of scope.
- **Top-N conditional format performance** — currently the top 10 / bottom
  10 rules re-rank the column on every render. For very wide result
  sets, a `metadata_cache`-style cache keyed by `(column, payload-hash)`
  would be a quick win.

---

## 16. Security & Privacy Notes

- The application listens on `0.0.0.0:8000` inside the container and is
  intended to be fronted by Nginx (see `nginx/nginx.conf`) for TLS
  termination in production.
- The SQLite file and the upload / log / report directories should be
  mounted as Docker volumes so they survive container restarts.
- The SMTP password is stored in plain text in `smtp_settings.password`
  — the `cryptography.fernet` hardening is on the V2 roadmap.
- The friendly error pages NEVER show stack traces or SQL details to the
  browser; the details are only written to the log file (visible to
  admins via the Log Viewer).
- The `error.html` template does not include any user-controlled data
  — only the application name and the status code.

---

## 17. Summary

Pivot App V1 is a self-contained internal operational tool that covers the
full workflow from "upload an Excel file" to "email a pivot report to a
stakeholder" to "soft-delete the underlying records" — with a polished
UI, friendly error handling, comprehensive logging, a self-documenting
diagnostics page, and a Settings page that lets the operator tune the
runtime without restarting the container.

It is production-ready as an **internal tool behind a VPN / SSO-protected
ingress**; deploying it as a public-facing service would require
authentication, SMTP password encryption, and a TLS-terminating reverse
proxy (all V2 items).
