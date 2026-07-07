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
from app.services.app_logging import configure_logging, log_event

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


# ---------------------------------------------------------------------------
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
    return _render_error_page(request, 400, "Bad request", str(detail))


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.exception("Unhandled error: %s", exc)
    log_event("error", "Unexpected error", details=str(exc), request=request)
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
    log_event("info", "Application started", details=f"version {__import__('app.models.app_settings', fromlist=['APP_VERSION']).APP_VERSION}")


@app.on_event("shutdown")
def on_shutdown():
    log_event("info", "Application stopped")
    logging.shutdown()
