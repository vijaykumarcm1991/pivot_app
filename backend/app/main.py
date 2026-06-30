"""
Pivot App — FastAPI entry point.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config.database import init_db
from app.routes.upload_routes import router as upload_router
from app.routes.dataset_routes import router as dataset_router
from app.routes.pivot_routes import router as pivot_router

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


# ---------------------------------------------------------------------------
# Startup event
# ---------------------------------------------------------------------------

@app.on_event("startup")
def on_startup():
    """Initialise the database on first run."""
    init_db()
