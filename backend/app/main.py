"""
Pivot App — FastAPI entry point.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config.database import init_db
from app.config.settings import LOG_DIR
from app.routes.upload_routes import router as upload_router
from app.routes.dataset_routes import router as dataset_router
from app.routes.pivot_routes import router as pivot_router
from app.routes.email_routes import router as email_router
from app.routes.settings_routes import router as settings_router
from app.routes.health_routes import router as health_router
from app.routes.log_routes import router as log_router
from app.routes.admin_routes import router as admin_router
from app.routes.user_directory_routes import router as user_directory_router
from app.services.app_logging import configure_logging, log_event
from app.services import user_directory

# ---------------------------------------------------------------------------
# Logging — must be configured BEFORE anything else logs anything.
# ---------------------------------------------------------------------------
configure_logging(LOG_DIR)
logger = logging.getLogger("pivot_app")

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Pivot App",
    description="Excel Pivot Analysis + Stakeholder Mailing Platform",
    version="1.0.0",
)

# CORS — allow all origins for internal tooling (tighten in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (CSS, JS)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Routers
app.include_router(upload_router)
app.include_router(dataset_router)
app.include_router(pivot_router)
app.include_router(email_router)
app.include_router(settings_router)
app.include_router(health_router)
app.include_router(log_router)
app.include_router(admin_router)
app.include_router(user_directory_router)


# ---------------------------------------------------------------------------
# Phase 8 — add Cache-Control: no-store to prevent the browser from
# caching the pivot page (which would cause stale `pivot.js` to load
# even after we ship a new version).
@app.middleware("http")
async def _add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path in (
        "/", "/pivot", "/manage", "/datasets", "/email/settings", "/email/history",
        "/admin/cleanup", "/admin/audit", "/diagnostics", "/logs", "/settings",
    ):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


# Custom error handlers — friendly pages, no stack traces.
# ---------------------------------------------------------------------------

def _render_error_page(request: Request, status_code: int, heading: str, message: str) -> HTMLResponse:
    """Render the friendly error template (no stack trace)."""
    from fastapi.templating import Jinja2Templates
    from app.config.settings import APP_NAME
    templates = Jinja2Templates(directory="app/templates")
    return templates.TemplateResponse(
        "error.html",
        {
            "request":     request,
            "status_code": status_code,
            "heading":     heading,
            "message":     message,
            "app_name":    APP_NAME,
        },
        status_code=status_code,
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    # API endpoints expect JSON, not the friendly HTML page.
    if request.url.path.startswith("/api/"):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return _render_error_page(
        request, 404,
        "Page not found",
        "The page or resource you requested does not exist on this server.",
    )


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc):
    return _render_error_page(
        request, 403,
        "Access denied",
        "You do not have permission to access this resource.",
    )


@app.exception_handler(400)
async def bad_request_handler(request: Request, exc):
    detail = getattr(exc, "detail", "The request could not be processed.")
    # API endpoints expect JSON, not the friendly HTML page — the
    # frontend's fetch().json() would throw "JSON.parse: unexpected
    # character at line 1 column 1" if we returned HTML here.  The
    # friendly error page is only meant for browser navigation.
    if request.url.path.startswith("/api/"):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"detail": str(detail)})
    return _render_error_page(request, 400, "Bad request", str(detail))


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.exception("Unhandled error: %s", exc)
    log_event("error", "Unexpected error", details=str(exc), request=request)
    # Same as above — API endpoints get JSON, browser navigations get
    # the friendly error page.
    if request.url.path.startswith("/api/"):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
    return _render_error_page(
        request, 500,
        "Something went wrong",
        "An unexpected error occurred. The application team has been notified. "
        "Please try again, or return to the previous page.",
    )


# ---------------------------------------------------------------------------
# Startup / shutdown events
# ---------------------------------------------------------------------------

@app.on_event("startup")
def on_startup():
    """Initialise the database on first run."""
    from app.models import (  # noqa: F401
        dataset, sheet, column,
        smtp_settings, email_history, recent_recipient,
        app_settings, app_log, soft_deleted_record, delete_audit, deleted_dataset,
    )
    init_db()
    # Load the user directory (users.json) into memory so the
    # email composer's typeahead works on the first request.
    # The service silently no-ops if the file is missing — the
    # admin page tells the user how to add it.
    try:
        user_directory.initial_load()
        status = user_directory.status()
        if status["totalUsers"] > 0:
            log_event(
                "info",
                "User directory loaded",
                category="startup",
                details=f"{status['enabledUsers']}/{status['totalUsers']} enabled users from {status['path']}",
            )
        else:
            log_event(
                "warning",
                "User directory not loaded",
                category="startup",
                details=f"no users at {status['path']} (typeahead will be empty until the file is uploaded)",
            )
    except Exception as exc:
        log_event(
            "error",
            "User directory failed to load",
            category="startup",
            details=str(exc),
        )
    log_event("info", "Application started", details=f"version {__import__('app.models.app_settings', fromlist=['APP_VERSION']).APP_VERSION}")


@app.on_event("shutdown")
def on_shutdown():
    log_event("info", "Application stopped")
    logging.shutdown()
